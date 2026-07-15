from app.agent.intent_parser import IntentParser
from app.agent.query_planner import QueryPlanner
from app.agent.sql_generator import SQLGenerator
from app.agent.sql_validator import SQLValidator


def test_total_population_uses_verified_column():
    intent = IntentParser().parse("What is the population of California?")
    plan, validation = QueryPlanner().create_plan(intent)
    assert validation.is_valid
    assert plan is not None
    assert plan.metric.estimate_column == "B01003e1"


def test_median_income_uses_non_sum_template():
    intent = IntentParser().parse("What is the median household income of California?")
    plan, validation = QueryPlanner().create_plan(intent)
    assert validation.is_valid
    assert plan is not None
    plan = SQLGenerator().generate(plan)
    assert "APPROX_PERCENTILE" in (plan.sql or "")
    assert "SUM(\"B19013e1\")" not in (plan.sql or "")


def test_sql_validator_rejects_delete():
    validator = SQLValidator()
    intent = IntentParser().parse("What is the population of California?")
    plan, _ = QueryPlanner().create_plan(intent)
    assert plan is not None
    plan.sql = "DELETE FROM census_table"
    assert validator.validate(plan).is_valid is False


def test_generated_sql_is_valid():
    intent = IntentParser().parse("Compare the populations of Texas and Florida")
    plan, validation = QueryPlanner().create_plan(intent)
    assert validation.is_valid
    assert plan is not None
    plan = SQLGenerator().generate(plan)
    assert SQLValidator().validate(plan).is_valid


def test_highest_state_population_is_ranking_without_named_geography():
    intent = IntentParser().parse("Which state has higher population in USA?")
    plan, validation = QueryPlanner().create_plan(intent)
    assert validation.is_valid
    assert plan is not None
    assert plan.query_type == "ranking"
    assert plan.geography_level == "state"
    assert plan.row_limit == 1


def test_threshold_state_population_filter():
    intent = IntentParser().parse("Which states have more than 10 million people?")
    plan, validation = QueryPlanner().create_plan(intent)
    assert validation.is_valid
    assert plan is not None
    assert plan.query_type == "filter"
    assert plan.threshold_value == 10_000_000


def test_age_breakdown_for_selected_state():
    intent = IntentParser().parse("Break California down by age.")
    plan, validation = QueryPlanner().create_plan(intent)
    assert validation.is_valid
    assert plan is not None
    assert plan.query_type == "age_breakdown"
    plan = SQLGenerator().generate(plan)
    assert SQLValidator().validate(plan).is_valid


def test_future_forecast_is_refused():
    intent = IntentParser().parse("Which state will have the highest population in 2040?")
    plan, validation = QueryPlanner().create_plan(intent)
    assert plan is None
    assert validation.is_valid is False
    assert "forecast" in (validation.reason or "")


def test_people_over_65_state_ranking_uses_composite_metric():
    intent = IntentParser().parse("which state has more no. of people greater than 65 age")
    plan, validation = QueryPlanner().create_plan(intent)
    assert validation.is_valid
    assert plan is not None
    assert plan.query_type == "ranking"
    assert plan.metric.metric_id == "population_by_age"
    assert plan.age_min == 65
    plan = SQLGenerator().generate(plan)
    assert "B01001e20" in plan.sql
    assert "B01003e1" not in plan.sql


def test_people_over_55_state_ranking_uses_dynamic_age_range():
    intent = IntentParser().parse("Which state has the most people age 55 and older?")
    plan, validation = QueryPlanner().create_plan(intent)
    assert validation.is_valid
    assert plan is not None
    assert plan.query_type == "ranking"
    assert plan.metric.metric_id == "population_by_age"
    assert plan.age_min == 55
    plan = SQLGenerator().generate(plan)
    assert "B01001e17" in plan.sql
    assert "B01001e41" in plan.sql
    assert "B01001e3" not in plan.sql


def test_less_people_over_55_is_lowest_state_ranking():
    intent = IntentParser().parse("Which state has the less people age 55 and older")
    plan, validation = QueryPlanner().create_plan(intent)
    assert validation.is_valid
    assert plan is not None
    assert plan.query_type == "ranking"
    assert plan.geography_level == "state"
    assert plan.sort_direction == "ascending"
    assert plan.metric.metric_id == "population_by_age"
    assert plan.age_min == 55


def test_age_percentage_uses_dynamic_denominator():
    intent = IntentParser().parse("What percentage of Florida residents are over 55?")
    plan, validation = QueryPlanner().create_plan(intent)
    assert validation.is_valid
    assert plan is not None
    assert plan.query_type == "aggregate_metric"
    assert plan.metric.metric_id == "population_by_age"
    assert plan.age_min == 55
    assert plan.value_kind == "percentage"
    plan = SQLGenerator().generate(plan)
    assert "100.0 *" in plan.sql
    assert "B01003e1" in plan.sql
    assert SQLValidator().validate(plan).is_valid


def test_state_ranking_filters_to_known_states():
    intent = IntentParser().parse("Which state has the highest poverty rate?")
    plan, validation = QueryPlanner().create_plan(intent)
    assert validation.is_valid
    assert plan is not None
    plan = SQLGenerator().generate(plan)
    assert "LEFT(\"CENSUS_BLOCK_GROUP\", 2) IN" in plan.sql
    assert "'72'" not in plan.sql


def test_income_without_definition_clarifies():
    intent = IntentParser().parse("Which state has the highest income?")
    plan, validation = QueryPlanner().create_plan(intent)
    assert plan is None
    assert validation.is_valid is False
    assert "median household income" in (validation.reason or "")


def test_nyc_resolves_as_city_county_set_lookup():
    intent = IntentParser().parse("What is the population of NYC?")
    plan, validation = QueryPlanner().create_plan(intent)
    assert validation.is_valid
    assert plan is not None
    assert plan.geography_filters[0]["type"] == "city"
    assert plan.geography_filters[0]["filter_method"] == "county_set"
