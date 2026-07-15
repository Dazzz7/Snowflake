from __future__ import annotations

import json
from typing import Any

from app.agent.hosted_llm_client import HostedLLMClient
from app.agent.narrow_sql_safety import enforce_row_limit, validate_narrow_sql
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
    "I can answer questions about US Census population, age, sex, race, and geographic or land-related data."
)


class NarrowLLMCensusAgent:
    def __init__(self, llm: HostedLLMClient | None = None) -> None:
        self.llm = llm if llm is not None else (HostedLLMClient() if settings.has_hosted_llm_config else None)

    def answer(self, question: str, session_id: str) -> AgentResponse:
        if not self.llm:
            return AgentResponse(
                answer="The narrowed Census agent requires the hosted LLM to be configured before it can answer.",
                status="llm_unavailable",
                interpretation={"llm_attempted": False, "supported_scope": ["population", "age", "sex", "race", "land", "geography"]},
            )

        state = session_store.get(session_id)
        context = self._conversation_context(state)
        scope = self._scope_question(question, context)
        if not scope.get("in_scope"):
            return AgentResponse(
                answer=OUT_OF_SCOPE_ANSWER,
                status="out_of_scope",
                interpretation={
                    "llm_attempted": True,
                    "llm_succeeded": bool(scope),
                    "llm_provider": settings.llm_model,
                    "scope_decision": scope,
                },
            )

        resolved_question = str(scope.get("resolved_question") or question)
        metadata_request = self._metadata_request(resolved_question, context)
        metadata_query = str(metadata_request.get("query") or resolved_question)
        metadata = search_metadata(metadata_query, self._safe_int(metadata_request.get("top_k"), 20))
        candidate_tables = self._candidate_tables(metadata_request, metadata)
        table_descriptions = [describe_table(table) for table in candidate_tables]
        samples = [
            inspect_sample_rows(
                item["table_name"],
                ["CENSUS_BLOCK_GROUP", *[column["column_name"] for column in item.get("columns", [])[1:4]]],
                limit=3,
            )
            for item in table_descriptions
            if not item.get("error")
        ]
        geography = lookup_geography(str(scope.get("geography_query") or scope.get("default_geography") or resolved_question))

        sql_payload = self._generate_sql(
            resolved_question=resolved_question,
            scope=scope,
            metadata=metadata,
            table_descriptions=table_descriptions,
            sample_rows=samples,
            geography=geography,
            retry_feedback=None,
        )
        sql = str(sql_payload.get("sql") or "").strip()
        sql = enforce_row_limit(sql)
        validation = validate_narrow_sql(sql)
        if not validation.is_valid:
            sql_payload = self._generate_sql(
                resolved_question=resolved_question,
                scope=scope,
                metadata=metadata,
                table_descriptions=table_descriptions,
                sample_rows=samples,
                geography=geography,
                retry_feedback=validation.reason,
            )
            sql = enforce_row_limit(str(sql_payload.get("sql") or "").strip())
            validation = validate_narrow_sql(sql)
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

        answer = self._generate_answer(resolved_question, scope, sql_payload, result.rows, table_descriptions)
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
                "described_tables": [item.get("table_name") for item in table_descriptions],
                "sql_payload": sql_payload,
            },
            evidence={
                "status": "llm_planned_sql_executed",
                "allowed_scope": ["population", "age", "sex", "race", "land", "geography"],
                "metadata_source": "Snowflake Census metadata restricted to B01, B02, and geography land table",
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

The agent supports only:
1. Population
2. Age
3. Sex
4. Race
5. Land and Census geography

A question is in scope when it requests data, comparisons, rankings, distributions, counts, percentages, or geographic
information related to those five subjects. Short follow-up questions may inherit meaning from conversation context.
If no state or other geography is supplied, interpret the question as the United States overall, unless the question asks
to rank or compare states, counties, Census Block Groups, or other geographies.

Return JSON only with keys:
in_scope, resolved_question, reason, default_geography, geography_query.
""".strip()
        return self.llm.generate_json(system, f"Conversation context: {json.dumps(context)}\nUser question: {question}") or {
            "in_scope": False,
            "resolved_question": question,
            "reason": "The LLM did not return a valid scope decision.",
        }

    def _metadata_request(self, resolved_question: str, context: dict[str, Any]) -> dict[str, Any]:
        system = """
You prepare metadata searches for a narrowed US Census agent.
Supported domains: population, age, sex, race, land, geography.
Return JSON only with keys: query, top_k, candidate_tables.
candidate_tables may include only 2020_CBG_B01, 2020_CBG_B02, 2020_METADATA_CBG_GEOGRAPHIC_DATA.
""".strip()
        payload = self.llm.generate_json(system, f"Conversation context: {json.dumps(context)}\nResolved question: {resolved_question}") or {}
        payload.setdefault("query", resolved_question)
        payload.setdefault("top_k", 20)
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
You are a careful US Census data analyst. You support only population, age, sex, race, land, and Census geography.

Use only these Snowflake tables:
- "{settings.snowflake_database}"."{settings.snowflake_schema}"."2020_CBG_B01"
- "{settings.snowflake_database}"."{settings.snowflake_schema}"."2020_CBG_B02"
- "{settings.snowflake_database}"."{settings.snowflake_schema}"."2020_METADATA_CBG_GEOGRAPHIC_DATA"

Rules:
1. Always use metadata labels before choosing columns.
2. Generate exactly one read-only SELECT or WITH query.
3. Use CENSUS_BLOCK_GROUP for geography.
4. For state filters use LEFT("CENSUS_BLOCK_GROUP", 2) = %(state_fips)s.
5. For state rankings/grouping use LEFT("CENSUS_BLOCK_GROUP", 2) AS state_fips.
6. If no geography is supplied and the question asks for a total, aggregate over the United States overall.
7. Include a LIMIT no larger than 500 for list/ranking queries.
8. Return JSON only with keys: sql, parameters, selected_columns, reasoning.
""".strip()
        user = {
            "resolved_question": resolved_question,
            "scope": scope,
            "geography_lookup": geography,
            "metadata_results": metadata.get("results", [])[:25],
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
        return self.llm.generate_text(system, json.dumps(user, default=str)) or "I queried Snowflake successfully, but the LLM did not return a final answer."

    def _candidate_tables(self, metadata_request: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
        requested = [str(table).upper() for table in metadata_request.get("candidate_tables", [])]
        tables = [table for table in requested if table in {"2020_CBG_B01", "2020_CBG_B02", "2020_METADATA_CBG_GEOGRAPHIC_DATA"}]
        for row in metadata.get("results", []):
            table = str(row.get("table_name") or "").upper()
            if table and table not in tables:
                tables.append(table)
        return tables[:3] or ["2020_CBG_B01", "2020_CBG_B02"]

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
