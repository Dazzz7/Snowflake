from app.agent.dynamic_semantic_layer import DynamicSemanticLayer
from app.agent.sql_generator import SQLGenerator
from app.agent.sql_validator import SQLValidator
from app.models.response_models import QueryResult


def fake_schema_result(rows):
    return QueryResult(rows=rows, columns=["TABLE_NAME", "COLUMN_NAME", "DATA_TYPE", "COMMENT"], query_id="schema-1")


def test_dynamic_semantic_layer_builds_validated_ranking_plan(monkeypatch):
    rows = [
        {"TABLE_NAME": "2019_CBG_PATTERNS", "COLUMN_NAME": "RAW_VISIT_COUNT", "DATA_TYPE": "NUMBER", "COMMENT": None},
        {"TABLE_NAME": "2019_CBG_PATTERNS", "COLUMN_NAME": "CENSUS_BLOCK_GROUP", "DATA_TYPE": "TEXT", "COMMENT": None},
    ]
    monkeypatch.setattr("app.agent.dynamic_semantic_layer.search_columns_metadata", lambda question, limit=30: fake_schema_result(rows))

    plan, validation, diagnostics = DynamicSemanticLayer(llm=None).create_plan("Which state has the highest raw visit count?")

    assert validation.is_valid
    assert plan is not None
    assert plan.query_type == "ranking"
    assert plan.metric.metric_id.startswith("dynamic_")
    assert diagnostics["validated_contract"]["value_column"] == "RAW_VISIT_COUNT"
    plan = SQLGenerator().generate(plan)
    assert "2019_CBG_PATTERNS" in plan.sql
    assert "RAW_VISIT_COUNT" in plan.sql
    assert SQLValidator().validate(plan).is_valid


def test_dynamic_semantic_layer_rejects_non_numeric_candidate(monkeypatch):
    rows = [
        {"TABLE_NAME": "2019_CBG_PATTERNS", "COLUMN_NAME": "TOP_BRANDS", "DATA_TYPE": "VARIANT", "COMMENT": None},
    ]
    monkeypatch.setattr("app.agent.dynamic_semantic_layer.search_columns_metadata", lambda question, limit=30: fake_schema_result(rows))

    plan, validation, diagnostics = DynamicSemanticLayer(llm=None).create_plan("Which state has the most top brands?")

    assert plan is None
    assert validation.is_valid is False
    assert diagnostics["eligible_candidates"] == []
