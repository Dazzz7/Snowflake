from __future__ import annotations

from app.agent.context_resolver import resolve_context
from app.agent.intent_parser import IntentParser
from app.agent.query_planner import QueryPlanner
from app.agent.response_generator import ResponseGenerator
from app.agent.result_validator import ResultValidator
from app.agent.sql_generator import SQLGenerator
from app.agent.sql_validator import SQLValidator
from app.catalog.metric_registry import load_metrics, load_taxonomy
from app.database.query_executor import SnowflakeQueryExecutor
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
            category_text = " ".join(
                f"{name.replace('_', ' ').title()}: {meta['description']}."
                for name, meta in taxonomy.items()
                if name != "geography"
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
                ),
                status="metadata",
                interpretation={
                    "question_type": "metadata",
                    "verified_metrics": list(metrics),
                    "supported_operations": ["lookup", "comparison", "ranking", "filter", "age_breakdown"],
                    "supported_geography_levels": ["state", "verified city county sets"],
                    "year": 2020,
                },
            )
        scope = classify_input(resolved_question)
        if not scope.in_scope:
            return AgentResponse(
                answer="I can help only with questions grounded in the available US Census dataset.",
                status="out_of_scope",
                interpretation={"reason": scope.reason},
            )

        intent = self.intent_parser.parse(resolved_question)
        plan, plan_validation = self.query_planner.create_plan(intent)
        if not plan_validation.is_valid or plan is None:
            return AgentResponse(
                answer=plan_validation.reason or "I could not construct a reliable Census query for that question.",
                status="needs_clarification" if intent.needs_clarification else "unsupported",
                interpretation={"resolved_question": resolved_question},
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
            ]
        )

    def _is_geography_correction(self, question: str) -> bool:
        lowered = question.lower().strip(" .")
        return lowered in {"ny is a state in usa", "ny is a state", "ny means new york state"}
