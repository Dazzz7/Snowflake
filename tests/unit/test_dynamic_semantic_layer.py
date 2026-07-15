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
    monkeypatch.setattr("app.agent.dynamic_semantic_layer.search_variable_metadata", lambda question, year=2020, limit=60: fake_schema_result([]))
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
    monkeypatch.setattr("app.agent.dynamic_semantic_layer.search_variable_metadata", lambda question, year=2020, limit=60: fake_schema_result([]))
    monkeypatch.setattr("app.agent.dynamic_semantic_layer.search_columns_metadata", lambda question, limit=30: fake_schema_result(rows))

    plan, validation, diagnostics = DynamicSemanticLayer(llm=None).create_plan("Which state has the most top brands?")

    assert plan is None
    assert validation.is_valid is False
    assert diagnostics["eligible_candidates"] == []


def test_veteran_question_uses_total_metadata_variable(monkeypatch):
    rows = [
        {
            "TABLE_NAME": "2020_CBG_B21",
            "COLUMN_NAME": "B21001e2",
            "DATA_TYPE": "FLOAT",
            "CONCEPT": "Sex By Age By Veteran Status For The Civilian Population 18 Years And Over",
            "LABEL": "Estimate: Civilian population 18 years and over: Total: Veteran",
            "UNIVERSE": "Civilian population 18 years and over",
            "IS_ESTIMATE": True,
            "IS_MARGIN_OF_ERROR": False,
        },
        {
            "TABLE_NAME": "2020_CBG_B21",
            "COLUMN_NAME": "B21001e5",
            "DATA_TYPE": "FLOAT",
            "CONCEPT": "Sex By Age By Veteran Status For The Civilian Population 18 Years And Over",
            "LABEL": "Estimate: Civilian population 18 years and over: Total: Male: Veteran",
            "UNIVERSE": "Civilian population 18 years and over",
            "IS_ESTIMATE": True,
            "IS_MARGIN_OF_ERROR": False,
        },
        {
            "TABLE_NAME": "2020_CBG_B21",
            "COLUMN_NAME": "B21001m2",
            "DATA_TYPE": "FLOAT",
            "CONCEPT": "Sex By Age By Veteran Status For The Civilian Population 18 Years And Over",
            "LABEL": "Margin of Error: Civilian population 18 years and over: Total: Veteran",
            "UNIVERSE": "Civilian population 18 years and over",
            "IS_ESTIMATE": False,
            "IS_MARGIN_OF_ERROR": True,
        },
    ]
    monkeypatch.setattr("app.agent.dynamic_semantic_layer.search_variable_metadata", lambda question, year=2020, limit=60: fake_schema_result(rows))

    plan, validation, diagnostics = DynamicSemanticLayer(llm=None).create_plan("how many veterans in Texas")

    assert validation.is_valid
    assert plan is not None
    assert plan.metric.display_name == "Veteran population"
    assert plan.metric.estimate_columns == ["B21001e2"]
    assert "B21001m2" not in plan.metric.estimate_columns
    assert diagnostics["validated_contract"]["selected_variable_labels"]["B21001E2"].endswith("Veteran")


def test_veteran_percentage_uses_total_universe_denominator(monkeypatch):
    rows = [
        {
            "TABLE_NAME": "2020_CBG_B21",
            "COLUMN_NAME": "B21001e1",
            "DATA_TYPE": "FLOAT",
            "TABLE_NUMBER": "B21001",
            "CONCEPT": "Sex By Age By Veteran Status For The Civilian Population 18 Years And Over",
            "LABEL": "Estimate: Civilian population 18 years and over: Total",
            "UNIVERSE": "Civilian population 18 years and over",
            "IS_ESTIMATE": True,
            "IS_MARGIN_OF_ERROR": False,
        },
        {
            "TABLE_NAME": "2020_CBG_B21",
            "COLUMN_NAME": "B21001e2",
            "DATA_TYPE": "FLOAT",
            "TABLE_NUMBER": "B21001",
            "CONCEPT": "Sex By Age By Veteran Status For The Civilian Population 18 Years And Over",
            "LABEL": "Estimate: Civilian population 18 years and over: Total: Veteran",
            "UNIVERSE": "Civilian population 18 years and over",
            "IS_ESTIMATE": True,
            "IS_MARGIN_OF_ERROR": False,
        },
        {
            "TABLE_NAME": "2020_CBG_B21",
            "COLUMN_NAME": "B21002e1",
            "DATA_TYPE": "FLOAT",
            "TABLE_NUMBER": "B21002",
            "CONCEPT": "Period Of Military Service For Civilian Veterans 18 Years And Over",
            "LABEL": "Estimate: Total: Civilian veterans 18 years and over",
            "UNIVERSE": "Civilian veterans 18 years and over",
            "IS_ESTIMATE": True,
            "IS_MARGIN_OF_ERROR": False,
        },
    ]
    monkeypatch.setattr("app.agent.dynamic_semantic_layer.search_variable_metadata", lambda question, year=2020, limit=60: fake_schema_result(rows))

    plan, validation, diagnostics = DynamicSemanticLayer(llm=None).create_plan("what percentage of Florida residents are veterans?")

    assert validation.is_valid
    assert plan is not None
    assert plan.metric.calculation == "rate"
    assert plan.metric.unit == "%"
    assert plan.metric.numerator_columns == ["B21001e2"]
    assert plan.metric.denominator_columns == ["B21001e1"]
    assert diagnostics["validated_contract"]["aggregation"] == "rate"


def test_dynamic_comparison_plan_uses_selected_geographies(monkeypatch):
    rows = [
        {
            "TABLE_NAME": "2020_CBG_B21",
            "COLUMN_NAME": "B21001e2",
            "DATA_TYPE": "FLOAT",
            "CONCEPT": "Sex By Age By Veteran Status For The Civilian Population 18 Years And Over",
            "LABEL": "Estimate: Civilian population 18 years and over: Total: Veteran",
            "UNIVERSE": "Civilian population 18 years and over",
            "IS_ESTIMATE": True,
            "IS_MARGIN_OF_ERROR": False,
        },
    ]
    monkeypatch.setattr("app.agent.dynamic_semantic_layer.search_variable_metadata", lambda question, year=2020, limit=60: fake_schema_result(rows))

    plan, validation, _ = DynamicSemanticLayer(llm=None).create_plan("Compare veteran populations in Texas and California")

    assert validation.is_valid
    assert plan is not None
    assert plan.query_type == "comparison"
    assert {item["name"] for item in plan.geography_filters} == {"Texas", "California"}


def test_rental_units_question_uses_direct_tenure_variable(monkeypatch):
    rows = [
        {
            "TABLE_NAME": "2020_CBG_B25",
            "COLUMN_NAME": "B25008e3",
            "DATA_TYPE": "FLOAT",
            "TABLE_NUMBER": "B25008",
            "CONCEPT": "Total Population In Occupied Housing Units By Tenure",
            "LABEL": "Estimate: Total population in occupied housing units: Total: Renter occupied",
            "UNIVERSE": "Total population in occupied housing units",
            "IS_ESTIMATE": True,
            "IS_MARGIN_OF_ERROR": False,
        },
        {
            "TABLE_NAME": "2020_CBG_B25",
            "COLUMN_NAME": "B25003e3",
            "DATA_TYPE": "FLOAT",
            "TABLE_NUMBER": "B25003",
            "CONCEPT": "Tenure",
            "LABEL": "Estimate: TENURE: Occupied housing units: Total: Renter occupied",
            "UNIVERSE": "Occupied housing units",
            "IS_ESTIMATE": True,
            "IS_MARGIN_OF_ERROR": False,
        },
    ]
    monkeypatch.setattr("app.agent.dynamic_semantic_layer.search_variable_metadata", lambda question, year=2020, limit=60: fake_schema_result(rows))

    plan, validation, diagnostics = DynamicSemanticLayer(llm=None).create_plan("Which Census Block Groups have over 100 rental units?")

    assert validation.is_valid
    assert plan is not None
    assert plan.query_type == "filter"
    assert plan.geography_level == "block_group"
    assert plan.threshold_operator == ">"
    assert plan.threshold_value == 100
    assert plan.metric.display_name == "Renter-occupied housing units"
    assert plan.metric.estimate_columns == ["B25003e3"]
    assert diagnostics["validated_contract"]["selected_variable_labels"]["B25003E3"].endswith("Renter occupied")


def test_average_age_per_state_builds_grouped_derived_metric():
    plan, validation, diagnostics = DynamicSemanticLayer(llm=None).create_plan("average age of residents per state in usa")

    assert validation.is_valid
    assert plan is not None
    assert plan.query_type == "grouped_metric"
    assert plan.geography_level == "state"
    assert plan.metric.metric_id == "dynamic_average_age"
    assert plan.metric.calculation == "weighted_average_age"
    assert "B01001e3" in plan.metric.source_columns
    assert diagnostics["validated_contract"]["operation"] == "grouped_metric"
