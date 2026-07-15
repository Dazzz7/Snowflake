from __future__ import annotations

import json
from typing import Any

from app.agent.hosted_llm_client import HostedLLMClient
from app.agent.narrow_sql_safety import enforce_row_limit, normalize_snowflake_identifiers, validate_narrow_sql
from app.agent.narrow_tools import (
    describe_table,
    enrich_geography_names,
    execute_sql,
    inspect_sample_rows,
    lookup_geography,
    search_metadata,
)
from app.config import settings
from app.memory.session_store import session_store
from app.models.response_models import AgentResponse


OUT_OF_SCOPE_ANSWER = (
    "I can answer questions related to the available Snowflake US Census dataset. I could not connect this question to that data."
)


class NarrowLLMCensusAgent:
    def __init__(self, llm: HostedLLMClient | None = None) -> None:
        self.llm = llm if llm is not None else (HostedLLMClient() if settings.has_hosted_llm_config else None)

    def answer(self, question: str, session_id: str) -> AgentResponse:
        if not self.llm:
            return AgentResponse(
                answer="The narrowed Census agent requires the hosted LLM to be configured before it can answer.",
                status="llm_unavailable",
                interpretation={"llm_attempted": False, "supported_scope": "available Snowflake US Census metadata"},
            )

        state = session_store.get(session_id)
        context = self._conversation_context(state)
        scope = self._scope_question(question, context)
        if scope.get("_llm_failed"):
            return AgentResponse(
                answer="The hosted LLM could not process the question right now. Please try again after the provider rate limit resets.",
                status="llm_unavailable",
                interpretation={
                    "llm_attempted": True,
                    "llm_succeeded": False,
                    "llm_provider": settings.llm_model,
                    "scope_decision": scope,
                    "llm_last_error": getattr(self.llm, "last_error", None),
                },
            )
        if not scope.get("in_scope"):
            return AgentResponse(
                answer=OUT_OF_SCOPE_ANSWER,
                status="out_of_scope",
                interpretation={
                    "llm_attempted": True,
                    "llm_succeeded": not scope.get("_llm_failed"),
                    "llm_provider": settings.llm_model,
                    "scope_decision": scope,
                },
            )

        resolved_question = str(scope.get("resolved_question") or question)
        metadata_request = self._metadata_request(resolved_question, context, scope)
        metadata = self._retrieve_metadata(metadata_request, resolved_question)
        if not metadata.get("results"):
            return AgentResponse(
                answer="I searched the Snowflake Census metadata but could not find relevant fields for that question.",
                status="no_metadata",
                interpretation={
                    "llm_attempted": True,
                    "llm_succeeded": True,
                    "llm_provider": settings.llm_model,
                    "scope_decision": scope,
                    "metadata_request": metadata_request,
                    "metadata_error": metadata.get("error"),
                },
            )
        candidate_tables = self._candidate_tables(metadata_request, metadata)
        table_descriptions = [describe_table(table) for table in candidate_tables]
        compact_descriptions = self._compact_table_descriptions(table_descriptions, metadata, resolved_question)
        approved_tables = self._approved_tables(compact_descriptions)
        approved_columns = self._approved_columns(compact_descriptions)
        samples = []
        geography = lookup_geography(str(scope.get("geography_query") or scope.get("default_geography") or resolved_question))

        sql_payload = self._generate_sql(
            resolved_question=resolved_question,
            scope=scope,
            metadata=metadata,
            table_descriptions=compact_descriptions,
            sample_rows=samples,
            geography=geography,
            retry_feedback=None,
        )
        sql = normalize_snowflake_identifiers(str(sql_payload.get("sql") or "").strip(), approved_tables, approved_columns)
        sql = enforce_row_limit(sql)
        validation = validate_narrow_sql(sql, approved_tables, approved_columns)
        if not validation.is_valid:
            sql_payload = self._generate_sql(
                resolved_question=resolved_question,
                scope=scope,
                metadata=metadata,
                table_descriptions=compact_descriptions,
                sample_rows=samples,
                geography=geography,
                retry_feedback=validation.reason,
            )
            sql = enforce_row_limit(normalize_snowflake_identifiers(str(sql_payload.get("sql") or "").strip(), approved_tables, approved_columns))
            validation = validate_narrow_sql(sql, approved_tables, approved_columns)
        if not validation.is_valid:
            return AgentResponse(
                answer="I could not produce a safe Snowflake SELECT query for this in-scope Census question.",
                status="invalid_sql",
                interpretation={
                    "llm_attempted": True,
                    "llm_succeeded": bool(sql_payload),
                    "llm_provider": settings.llm_model,
                    "scope_decision": scope,
                    "metadata_request": metadata_request,
                    "sql_validation_error": validation.reason,
                    "sql_payload": sql_payload,
                    "llm_last_error": getattr(self.llm, "last_error", None),
                },
                sql=sql or None,
            )

        parameters = sql_payload.get("parameters") if isinstance(sql_payload.get("parameters"), dict) else {}
        result = execute_sql(sql, parameters)
        result.rows = enrich_geography_names(result.rows)
        if result.error:
            return AgentResponse(
                answer=result.error,
                status="invalid_result",
                interpretation={
                    "llm_attempted": True,
                    "llm_succeeded": True,
                    "llm_provider": settings.llm_model,
                    "scope_decision": scope,
                    "metadata_request": metadata_request,
                    "sql_payload": sql_payload,
                },
                sql=sql,
            )

        answer = self._generate_answer(resolved_question, scope, sql_payload, result.rows, compact_descriptions)
        self._remember(state, resolved_question, answer, result.rows, sql_payload)
        return AgentResponse(
            answer=answer,
            status="success",
            interpretation={
                "llm_attempted": True,
                "llm_succeeded": True,
                "llm_provider": settings.llm_model,
                "scope_decision": scope,
                "metadata_request": metadata_request,
                "metadata_results": metadata.get("results", [])[:12],
                "described_tables": [item.get("table_name") for item in compact_descriptions],
                "sql_payload": sql_payload,
            },
            evidence={
                "status": "llm_planned_sql_executed",
                "metadata_source": "Question-specific Snowflake Census metadata retrieval",
                "approved_tables": sorted(approved_tables),
                "approved_column_count": len(approved_columns),
                "row_count": len(result.rows),
                "query_id": result.query_id,
                "query_duration_ms": result.query_duration_ms,
            },
            sql=sql,
            rows=result.rows,
        )

    def _scope_question(self, question: str, context: dict[str, Any]) -> dict[str, Any]:
        system = """
You are the scope controller for a US Census analytics agent.

The agent can answer questions that are plausibly related to the available Snowflake US Census / Census Block Group
dataset. This may include demographic, social, economic, housing, household, commuting, education, health-insurance,
poverty, income, race, age, sex, population, and geography questions when the fields can be found in metadata.

A question is out of scope when it is unrelated to the Census dataset, asks for private/non-dataset facts, asks for
unverified forecasts, or asks for data products that are clearly not in Census metadata. If a question is plausibly about
Census data but you are not sure whether a field exists, mark it in scope so the metadata retrieval step can verify it.

Short follow-up questions may inherit meaning from conversation context. If no state or other geography is supplied,
interpret the question as the United States overall unless the question asks to rank or compare geographies.

Also prepare a targeted metadata search if the question is in scope. Do not ask for the full schema.
Use natural Census metadata language, not code-like names. For example, for "rental units" use metadata phrases such as
"renter occupied housing units tenure".

Return JSON only with keys:
in_scope, resolved_question, reason, default_geography, geography_query, metadata_query, metadata_queries, metadata_top_k.
""".strip()
        return self.llm.generate_json(system, f"Conversation context: {json.dumps(context)}\nUser question: {question}") or {
            "in_scope": False,
            "resolved_question": question,
            "reason": "The LLM did not return a valid scope decision.",
            "_llm_failed": True,
            "llm_error": getattr(self.llm, "last_error", None),
        }

    def _metadata_request(self, resolved_question: str, context: dict[str, Any], scope: dict[str, Any] | None = None) -> dict[str, Any]:
        if scope and (scope.get("metadata_query") or scope.get("metadata_queries")):
            query = str(scope.get("metadata_query") or resolved_question)
            queries = scope.get("metadata_queries") if isinstance(scope.get("metadata_queries"), list) else [query]
            return {
                "query": query,
                "queries": queries,
                "top_k": self._safe_int(scope.get("metadata_top_k"), 30),
                "candidate_tables": [],
                "source": "scope_llm",
            }
        system = """
You prepare targeted metadata searches for a Snowflake US Census agent.

Do not ask for the entire schema. Create only the smallest set of search phrases needed to find the fields for the
question. Use Census-style terms when helpful, such as universe, households, occupied housing units, poverty, income,
rent, insurance, education, commuting, race, age, sex, population, land area, or Census Block Group.
Prefer natural Census labels over code-like or underscored phrases. For example, user wording like "rental units"
should search for "renter occupied housing units tenure".

Return JSON only with keys: query, queries, top_k, candidate_tables.
- query: the best single metadata search phrase.
- queries: 1 to 4 short alternative metadata search phrases.
- top_k: number of metadata rows to retrieve, usually 30 to 60.
- candidate_tables: optional table names only if you are confident; otherwise [].
""".strip()
        payload = self.llm.generate_json(system, f"Conversation context: {json.dumps(context)}\nResolved question: {resolved_question}") or {}
        payload.setdefault("query", resolved_question)
        payload.setdefault("queries", [payload["query"]])
        payload.setdefault("top_k", 30)
        return payload

    def _generate_sql(
        self,
        resolved_question: str,
        scope: dict[str, Any],
        metadata: dict[str, Any],
        table_descriptions: list[dict[str, Any]],
        sample_rows: list[dict[str, Any]],
        geography: dict[str, Any],
        retry_feedback: str | None,
    ) -> dict[str, Any]:
        system = f"""
You are a careful US Census data analyst writing SQL for Snowflake.

Use only the Snowflake tables and columns provided in table_descriptions. They are the retrieved metadata candidates for
this question. Do not invent tables or columns. If the provided metadata is not enough to answer the question, return an
empty sql string and explain the missing field in reasoning.

Rules:
1. Always use metadata labels before choosing columns.
2. Generate exactly one read-only SELECT or WITH query.
3. Use CENSUS_BLOCK_GROUP for geography.
4. For state filters use LEFT("CENSUS_BLOCK_GROUP", 2) = %(state_fips)s.
5. For state rankings/grouping use LEFT("CENSUS_BLOCK_GROUP", 2) AS state_fips.
6. If no geography is supplied and the question asks for a total, aggregate over the United States overall.
7. Use additive aggregation only for count-like estimate columns. Do not average medians or percentages unless the
   question explicitly asks for an approximate/unweighted summary and you label it that way.
8. Include a LIMIT no larger than 500 for list/ranking queries.
9. Return JSON only with keys: sql, parameters, selected_columns, reasoning.
""".strip()
        user = {
            "resolved_question": resolved_question,
            "scope": scope,
            "geography_lookup": geography,
            "metadata_results": self._compact_metadata_results(metadata.get("results", []))[:15],
            "table_descriptions": table_descriptions,
            "sample_rows": sample_rows,
            "retry_feedback": retry_feedback,
        }
        return self.llm.generate_json(system, json.dumps(user, default=str)) or {}

    def _generate_answer(
        self,
        resolved_question: str,
        scope: dict[str, Any],
        sql_payload: dict[str, Any],
        rows: list[dict[str, Any]],
        table_descriptions: list[dict[str, Any]],
    ) -> str:
        system = """
You are a concise US Census data analyst. Answer only from the Snowflake rows provided.
State the year, geography, result, and what the selected data means. Do not invent numbers.
If rows include STATE_NAME, use it instead of only FIPS. Keep the answer compact.
""".strip()
        user = {
            "question": resolved_question,
            "scope": scope,
            "sql_payload": sql_payload,
            "rows": rows[:80],
            "table_descriptions_used": [
                {
                    "table_name": item.get("table_name"),
                    "description": item.get("description"),
                    "columns": item.get("columns", [])[:80],
                }
                for item in table_descriptions
            ],
        }
        generated = self.llm.generate_text(system, json.dumps(user, default=str))
        if generated:
            return generated
        return self._fallback_answer(resolved_question, rows)

    def _fallback_answer(self, resolved_question: str, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "The Snowflake query completed, but it returned no rows for this Census question."

        first_row = rows[0]
        if len(rows) == 1:
            values = ", ".join(
                f"{str(key).replace('_', ' ')} = {self._format_value(value)}"
                for key, value in first_row.items()
            )
            return f"Using the available 2020 Census data for '{resolved_question}', Snowflake returned: {values}."

        preview = []
        for row in rows[:10]:
            preview.append(
                "; ".join(
                    f"{str(key).replace('_', ' ')} = {self._format_value(value)}"
                    for key, value in row.items()
                )
            )
        return f"Using the available 2020 Census data for '{resolved_question}', Snowflake returned {len(rows)} rows. Top rows: " + " | ".join(preview)

    def _format_value(self, value: Any) -> str:
        if isinstance(value, int):
            return f"{value:,}"
        if isinstance(value, float):
            return f"{value:,.2f}"
        return str(value)

    def _candidate_tables(self, metadata_request: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
        metadata_tables = {
            str(row.get("table_name") or "").upper()
            for row in metadata.get("results", [])
            if row.get("table_name")
        }
        requested = [
            str(table).upper()
            for table in metadata_request.get("candidate_tables", [])
            if str(table).upper() in metadata_tables
        ]
        tables = list(dict.fromkeys(requested))
        for row in metadata.get("results", []):
            table = str(row.get("table_name") or "").upper()
            if table and table not in tables:
                tables.append(table)
        return tables[:3]

    def _retrieve_metadata(self, metadata_request: dict[str, Any], resolved_question: str) -> dict[str, Any]:
        raw_queries = metadata_request.get("queries")
        if isinstance(raw_queries, list):
            queries = [str(query).strip() for query in raw_queries if str(query).strip()]
        else:
            queries = []
        query = str(metadata_request.get("query") or resolved_question).strip()
        if query:
            queries.insert(0, query)
        queries.append(resolved_question)
        queries.extend(self._metadata_query_expansions(" ".join(queries)))
        queries = list(dict.fromkeys(queries))[:5]

        rows: list[dict[str, Any]] = []
        errors = []
        top_k = self._safe_int(metadata_request.get("top_k"), 30)
        per_query_limit = max(8, min(top_k, 30))
        for item in queries:
            result = search_metadata(item, per_query_limit)
            if result.get("error"):
                errors.append(result["error"])
            rows.extend(result.get("results", []))
        return {
            "results": self._dedupe_metadata(rows)[: max(12, min(top_k, 40))],
            "queries": queries,
            "error": "; ".join(errors) if errors else None,
        }

    def _compact_table_descriptions(
        self,
        table_descriptions: list[dict[str, Any]],
        metadata: dict[str, Any],
        question: str,
    ) -> list[dict[str, Any]]:
        selected_by_table: dict[str, set[str]] = {}
        selected_rows_by_table: dict[str, dict[str, dict[str, Any]]] = {}
        for row in metadata.get("results", [])[:25]:
            table = str(row.get("table_name") or "").upper()
            column = str(row.get("column_name") or "")
            if table and column:
                selected_by_table.setdefault(table, set()).add(column.upper())
                selected_rows_by_table.setdefault(table, {})[column.upper()] = row

        compact = []
        for table in table_descriptions:
            table_name = str(table.get("table_name") or "").upper()
            keep_columns = {"CENSUS_BLOCK_GROUP", *selected_by_table.get(table_name, set())}
            if table_name == "2020_METADATA_CBG_GEOGRAPHIC_DATA":
                keep_columns.update({"AMOUNT_LAND", "AMOUNT_WATER", "LATITUDE", "LONGITUDE"})

            columns = []
            for column in table.get("columns", []):
                column_name = str(column.get("column_name") or "")
                if column_name.upper() not in keep_columns:
                    continue
                columns.append(
                    {
                        "column_name": column_name,
                    "label": self._short_label(str(column.get("label") or "")),
                        "concept": column.get("concept"),
                        "universe": column.get("universe"),
                    }
                )
            existing = {str(column.get("column_name") or "").upper() for column in columns}
            for column_name in keep_columns:
                if column_name in existing or column_name == "CENSUS_BLOCK_GROUP":
                    continue
                metadata_row = selected_rows_by_table.get(table_name, {}).get(column_name)
                if not metadata_row:
                    continue
                columns.append(
                    {
                        "column_name": metadata_row.get("column_name"),
                        "label": self._short_label(str(metadata_row.get("label") or "")),
                        "concept": metadata_row.get("concept"),
                        "universe": metadata_row.get("universe"),
                    }
                )
            compact.append(
                {
                    "table_name": table_name,
                    "description": table.get("description"),
                    "geography_column": table.get("geography_column"),
                    "columns": columns[:30],
                    "error": table.get("error"),
                }
            )
        return compact

    def _compact_metadata_results(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compact = []
        for row in rows:
            compact.append(
                {
                    "table_name": row.get("table_name"),
                    "column_name": row.get("column_name"),
                    "label": self._short_label(str(row.get("label") or "")),
                    "universe": row.get("universe"),
                    "category": row.get("category"),
                }
            )
        return compact

    def _approved_tables(self, table_descriptions: list[dict[str, Any]]) -> set[str]:
        return {
            str(item.get("table_name") or "").upper()
            for item in table_descriptions
            if item.get("table_name") and not item.get("error")
        }

    def _approved_columns(self, table_descriptions: list[dict[str, Any]]) -> set[str]:
        columns = {"CENSUS_BLOCK_GROUP"}
        for item in table_descriptions:
            for column in item.get("columns", []):
                column_name = str(column.get("column_name") or "")
                if column_name:
                    columns.add(column_name)
        return columns

    def _dedupe_metadata(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[str, str]] = set()
        deduped = []
        for row in rows:
            key = (str(row.get("table_name") or "").upper(), str(row.get("column_name") or "").upper())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        return deduped

    def _metadata_query_expansions(self, text: str) -> list[str]:
        normalized = text.lower().replace("_", " ")
        expansions = []
        if any(term in normalized for term in ["rental unit", "rental housing", "renter occupied", "rental units"]):
            expansions.append("renter occupied housing units tenure")
        return expansions

    def _short_label(self, label: str) -> str:
        for prefix in [
            "Estimate: SEX BY AGE: ",
            "Estimate: RACE: ",
            "Estimate: TOTAL POPULATION: ",
        ]:
            label = label.replace(prefix, "")
        return label[:140]

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _conversation_context(self, state: Any) -> dict[str, Any]:
        return {
            "last_question": getattr(state, "last_resolved_question", None),
            "last_answer": getattr(state, "last_answer", None),
            "last_sql_payload": getattr(state, "last_sql_payload", None),
            "last_rows": getattr(state, "last_result_set", [])[:5],
        }

    def _remember(self, state: Any, question: str, answer: str, rows: list[dict[str, Any]], sql_payload: dict[str, Any]) -> None:
        state.last_resolved_question = question
        state.last_answer = answer
        state.last_sql_payload = sql_payload
        state.last_result_set = rows
