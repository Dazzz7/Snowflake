from __future__ import annotations

from app.agent.context_resolver import resolve_context
from app.agent.dynamic_semantic_layer import DynamicSemanticLayer
from app.agent.intent_parser import IntentParser
from app.agent.query_planner import QueryPlanner
from app.agent.response_generator import ResponseGenerator
from app.agent.result_validator import ResultValidator
from app.agent.sql_generator import SQLGenerator
from app.agent.sql_validator import SQLValidator
from app.catalog.metric_registry import load_metrics, load_taxonomy
from app.catalog.catalog_search import summarize_schema_matches
from app.database.query_executor import SnowflakeQueryExecutor
from app.database.schema_loader import search_columns_metadata
from app.guardrails.input_guardrail import classify_input
from app.memory.session_store import session_store
from app.models.response_models import AgentResponse


class CensusChatAgent:
    def __init__(self) -> None:
        self.intent_parser = IntentParser()
        self.query_planner = QueryPlanner()
        self.sql_generator = SQLGenerator()
        self.sql_validator = SQLValidator()
        self.executor = SnowflakeQueryExecutor()
        self.result_validator = ResultValidator()
        self.response_generator = ResponseGenerator()
        self.dynamic_semantic_layer = DynamicSemanticLayer()

    def answer(self, question: str, session_id: str) -> AgentResponse:
        state = session_store.get(session_id)
        resolved_question = resolve_context(question, state)
        if self._is_geography_correction(resolved_question):
            return AgentResponse(
                answer='Yes. "NY" commonly refers to New York State, while "NYC" refers specifically to New York City. I will keep that distinction in this conversation.',
                status="acknowledged",
                interpretation={
                    "question_type": "geography_correction",
                    "alias": "NY",
                    "meaning": "New York State",
                    "city_alias": "NYC",
                    "city_meaning": "New York City",
                },
            )
        if self._is_capability_question(resolved_question):
            taxonomy = load_taxonomy()
            metrics = load_metrics()
            schema_result = search_columns_metadata(resolved_question, limit=12)
            schema_matches = [] if schema_result.error else summarize_schema_matches(schema_result.rows, limit=12)
            category_text = " ".join(
                f"{name.replace('_', ' ').title()}: {meta['description']}."
                for name, meta in taxonomy.items()
                if name != "geography"
            )
            schema_text = ""
            if schema_matches:
                schema_text = (
                    " I also searched the live Snowflake metadata for your wording and found fields such as "
                    + "; ".join(f"{item['table']}.{item['column']} ({item['type']})" for item in schema_matches[:6])
                    + "."
                )
            return AgentResponse(
                answer=(
                    "I can answer questions grounded in the available US Census data across several categories. "
                    + category_text
                    + " The underlying dataset contains thousands of Census attributes. Common metrics are mapped and "
                    + "validated explicitly for reliability, including "
                    + ", ".join(metric.display_name for metric in metrics.values())
                    + ". I can perform lookups, comparisons, rankings, threshold filters, and demographic breakdowns "
                    + "across supported geographic levels. For ambiguous measures such as income, I will ask which definition you mean."
                    + schema_text
                ),
                status="metadata",
                interpretation={
                    "question_type": "metadata",
                    "verified_metrics": list(metrics),
                    "supported_operations": ["lookup", "comparison", "ranking", "filter", "age_breakdown"],
                    "supported_geography_levels": ["state", "verified city county sets"],
                    "year": 2020,
                    "live_schema_search_attempted": True,
                    "live_schema_query_id": schema_result.query_id,
                    "live_schema_error": schema_result.error,
                },
                evidence={
                    "status": "metadata_verified" if schema_matches else "metadata_unavailable",
                    "operation": {
                        "operation": "search_live_schema_metadata",
                        "query": resolved_question,
                        "source": "Snowflake INFORMATION_SCHEMA.COLUMNS",
                        "limit": 12,
                    },
                    "schema_matches": schema_matches,
                    "provenance": {
                        "query_id": schema_result.query_id,
                        "source": "US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET.INFORMATION_SCHEMA.COLUMNS",
                    },
                    "answer_policy": "metadata_bound",
                },
            )
        scope = classify_input(resolved_question)
        if not scope.in_scope:
            return AgentResponse(
                answer="I can help only with questions grounded in the available US Census dataset.",
                status="out_of_scope",
                interpretation={"reason": scope.reason},
            )

        if self._should_try_dynamic_semantic_first(resolved_question):
            dynamic_response = self._try_dynamic_semantic_plan(resolved_question)
            if dynamic_response:
                return dynamic_response

        intent = self.intent_parser.parse(resolved_question)
        plan, plan_validation = self.query_planner.create_plan(intent)
        if not plan_validation.is_valid or plan is None:
            dynamic_response = self._try_dynamic_semantic_plan(resolved_question)
            if dynamic_response:
                return dynamic_response
            schema_response = self._metadata_fallback_response(resolved_question, plan_validation.reason)
            if schema_response:
                return schema_response
            return AgentResponse(
                answer=plan_validation.reason or "I could not construct a reliable Census query for that question.",
                status="needs_clarification" if intent.needs_clarification else "unsupported",
                interpretation={
                    "resolved_question": resolved_question,
                    "llm_attempted": intent.llm_attempted,
                    "llm_succeeded": intent.llm_succeeded,
                    "llm_provider": intent.llm_provider,
                },
            )

        plan = self.sql_generator.generate(plan)
        sql_validation = self.sql_validator.validate(plan)
        if not sql_validation.is_valid:
            return AgentResponse(
                answer="I could not construct a safe verified query for that question, so I am not returning an unverified answer.",
                status="invalid_sql",
                interpretation={"reason": sql_validation.reason},
            )

        result = self.executor.execute(plan.sql or "", plan.parameters)
        result_validation = self.result_validator.validate(plan, result)
        if not result_validation.is_valid:
            return AgentResponse(
                answer=result_validation.reason or "The Census query did not produce a valid result.",
                status="invalid_result",
                interpretation={
                    "resolved_question": resolved_question,
                    "metric": plan.metric.display_name,
                    "source_table": plan.metric.table,
                    "source_columns": plan.metric.source_columns or plan.metric.estimate_columns,
                },
                sql=plan.sql,
            )

        state.remember(
            intent.metric,
            intent.geographies,
            plan.metric.year,
            intent.intent,
            geography_level=plan.geography_level,
            geography_scope=plan.geography_scope,
            operation_type=plan.operation_type,
            sort_direction=plan.sort_direction,
            limit=plan.row_limit,
            result_rows=result.rows,
        )
        return self.response_generator.generate(resolved_question, plan, result)

    def _try_dynamic_semantic_plan(self, question: str) -> AgentResponse | None:
        plan, validation, diagnostics = self.dynamic_semantic_layer.create_plan(question)
        if not validation.is_valid or plan is None:
            return None
        plan = self.sql_generator.generate(plan)
        sql_validation = self.sql_validator.validate(plan)
        if not sql_validation.is_valid:
            return AgentResponse(
                answer="I found matching live metadata, but the generated dynamic plan did not pass SQL validation.",
                status="invalid_sql",
                interpretation={
                    "question_type": "dynamic_semantic_plan",
                    "reason": sql_validation.reason,
                    "dynamic_semantic_diagnostics": diagnostics,
                },
                sql=plan.sql,
            )
        result = self.executor.execute(plan.sql or "", plan.parameters)
        result_validation = self.result_validator.validate(plan, result)
        if not result_validation.is_valid:
            return AgentResponse(
                answer=result_validation.reason or "The dynamic Census query did not produce a valid result.",
                status="invalid_result",
                interpretation={
                    "question_type": "dynamic_semantic_plan",
                    "reason": result_validation.reason,
                    "dynamic_semantic_diagnostics": diagnostics,
                },
                sql=plan.sql,
            )
        response = self.response_generator.generate(question, plan, result)
        response.interpretation["dynamic_semantic_layer"] = {
            "used": True,
            "schema_query_id": diagnostics.get("schema_query_id"),
            "eligible_candidates": diagnostics.get("eligible_candidates"),
            "validated_contract": diagnostics.get("validated_contract"),
        }
        response.evidence["dynamic_semantic_layer"] = {
            "used": True,
            "contract": diagnostics.get("validated_contract"),
            "schema_matches": diagnostics.get("eligible_candidates"),
        }
        return response

    def _is_capability_question(self, question: str) -> bool:
        lowered = question.lower()
        return any(
            phrase in lowered
            for phrase in [
                "what data",
                "what kind of data",
                "what can you answer",
                "what can you do",
                "what can i ask",
                "topics can i ask",
                "which years are available",
                "geographic levels",
                "columns",
                "fields",
                "schema",
                "metadata",
            ]
        )

    def _metadata_fallback_response(self, question: str, failure_reason: str | None) -> AgentResponse | None:
        lowered = question.lower()
        if not any(term in lowered for term in ["column", "field", "schema", "metadata", "available", "data about", "have about"]):
            return None
        schema_result = search_columns_metadata(question, limit=12)
        if schema_result.error or not schema_result.rows:
            return None
        schema_matches = summarize_schema_matches(schema_result.rows, limit=12)
        answer = (
            "I could not map that to a pre-verified analytical plan yet, but I searched the live Snowflake metadata and found: "
            + "; ".join(f"{item['table']}.{item['column']} ({item['type']})" for item in schema_matches[:8])
            + ". I can use these metadata hits to build a validated analysis when the requested operation, geography, and aggregation are clear."
        )
        return AgentResponse(
            answer=answer,
            status="metadata",
            interpretation={
                "question_type": "metadata_fallback",
                "planning_failure": failure_reason,
                "live_schema_search_attempted": True,
                "live_schema_query_id": schema_result.query_id,
            },
            evidence={
                "status": "metadata_verified",
                "operation": {
                    "operation": "search_live_schema_metadata",
                    "query": question,
                    "source": "Snowflake INFORMATION_SCHEMA.COLUMNS",
                    "limit": 12,
                },
                "schema_matches": schema_matches,
                "provenance": {
                    "query_id": schema_result.query_id,
                    "source": "US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET.INFORMATION_SCHEMA.COLUMNS",
                },
                "answer_policy": "metadata_bound",
            },
        )

    def _should_try_dynamic_semantic_first(self, question: str) -> bool:
        lowered = question.lower()
        dynamic_terms = [
            "raw visit",
            "visitor count",
            "visit count",
            "distance from home",
            "top brand",
            "top brands",
            "same day brand",
            "same month brand",
            "popularity by",
            "amount land",
        ]
        return any(term in lowered for term in dynamic_terms)

    def _is_geography_correction(self, question: str) -> bool:
        lowered = question.lower().strip(" .")
        return lowered in {"ny is a state in usa", "ny is a state", "ny means new york state"}
