from app.agent.intent_parser import IntentParser
from app.agent.query_planner import QueryPlanner
from app.agent.response_generator import ResponseGenerator
from app.agent.result_validator import ResultValidator
from app.agent.sql_generator import SQLGenerator
from app.models.response_models import QueryResult


def _plan_for(question: str):
    intent = IntentParser().parse(question)
    plan, validation = QueryPlanner().create_plan(intent)
    assert validation.is_valid
    assert plan is not None
    return SQLGenerator().generate(plan)


def test_ranking_response_includes_typed_claim_and_operation_contract():
    plan = _plan_for("Which state has the highest population?")
    result = QueryResult(
        rows=[{"STATE_FIPS": "06", "VALUE": 39_538_223}],
        columns=["STATE_FIPS", "VALUE"],
        query_id="01abc",
        query_duration_ms=123,
    )

    response = ResponseGenerator().generate("Which state has the highest population?", plan, result)
    evidence = response.evidence

    assert evidence["status"] == "verified"
    assert evidence["claim"]["geography"] == "California"
    assert evidence["claim"]["value"] == 39_538_223
    assert evidence["claim"]["unit"] == "people"
    assert evidence["claim"]["metric_id"] == "total_population"
    assert evidence["claim"]["source_variable"] == "B01003_001E"
    assert evidence["operation"]["operation"] == "rank"
    assert evidence["operation"]["sort"] == {"field": "metric_value", "direction": "desc"}
    assert evidence["operation"]["geography_level"] == "state"
    assert evidence["provenance"]["query_id"] == "01abc"
    assert evidence["answer_policy"] == "evidence_bound"


def test_dynamic_age_evidence_lists_selected_age_variables():
    plan = _plan_for("Which state has the most people age 55 and older?")
    result = QueryResult(
        rows=[{"STATE_FIPS": "06", "VALUE": 10_400_000}],
        columns=["STATE_FIPS", "VALUE"],
        query_id="age-query",
    )

    response = ResponseGenerator().generate("Which state has the most people age 55 and older?", plan, result)
    evidence = response.evidence

    assert evidence["operation"]["dimension_filter"]["min"] == 55
    assert "B01001_017E" in evidence["claim"]["source_variables"]
    assert "B01001_003E" not in evidence["claim"]["source_variables"]


def test_result_validator_rejects_unknown_state_fips():
    plan = _plan_for("Which state has the highest poverty rate?")
    result = QueryResult(rows=[{"STATE_FIPS": "72", "VALUE": 43.4}], columns=["STATE_FIPS", "VALUE"])

    validation = ResultValidator().validate(plan, result)

    assert validation.is_valid is False
    assert "approved state scope" in (validation.reason or "")
