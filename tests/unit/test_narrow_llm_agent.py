from app.agent.narrow_llm_agent import NarrowLLMCensusAgent
from app.agent.narrow_sql_safety import normalize_snowflake_identifiers
from app.models.response_models import QueryResult


class QueueLLM:
    def __init__(self, json_payloads, text="final answer"):
        self.json_payloads = list(json_payloads)
        self.text = text

    def generate_json(self, system, user):
        assert self.json_payloads
        return self.json_payloads.pop(0)

    def generate_text(self, system, user):
        return self.text


class FailingLLM:
    last_error = "LLM HTTP error 429."

    def generate_json(self, system, user):
        return None

    def generate_text(self, system, user):
        return None


def test_narrow_agent_requires_llm():
    response = NarrowLLMCensusAgent(llm=None).answer("What is the US population?", "no-llm-test")

    assert response.status == "llm_unavailable"


def test_narrow_agent_rejects_out_of_scope_from_llm():
    llm = QueueLLM(
        [
            {
                "in_scope": False,
                "resolved_question": "What is the median income in Texas?",
                "reason": "The question is outside the available Census metadata.",
            }
        ]
    )

    response = NarrowLLMCensusAgent(llm=llm).answer("What is the median income in Texas?", "scope-test")

    assert response.status == "out_of_scope"
    assert "Snowflake US Census dataset" in response.answer
    assert response.interpretation["scope_decision"]["in_scope"] is False


def test_narrow_agent_runs_llm_sql_flow(monkeypatch):
    llm = QueueLLM(
        [
            {
                "in_scope": True,
                "resolved_question": "What is the population of California?",
                "default_geography": None,
                "geography_query": "California",
                "reason": "Population is in scope.",
            },
            {"query": "total population", "top_k": 20, "candidate_tables": ["2020_CBG_B01"]},
            {
                "sql": 'SELECT SUM("B01003e1") AS total_population FROM "US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET"."PUBLIC"."2020_CBG_B01" WHERE LEFT("CENSUS_BLOCK_GROUP", 2) = %(state_fips)s',
                "parameters": {"state_fips": "06"},
                "selected_columns": ["B01003e1"],
                "reasoning": "Use total population and California FIPS.",
            },
        ],
        text="California had 39,538,223 residents in the 2020 dataset.",
    )
    monkeypatch.setattr(
        "app.agent.narrow_llm_agent.search_metadata",
        lambda query, top_k=20: {"results": [{"table_name": "2020_CBG_B01", "column_name": "B01003e1"}]},
    )
    monkeypatch.setattr(
        "app.agent.narrow_llm_agent.describe_table",
        lambda table: {"table_name": table, "columns": [{"column_name": "CENSUS_BLOCK_GROUP"}, {"column_name": "B01003e1"}]},
    )
    monkeypatch.setattr("app.agent.narrow_llm_agent.inspect_sample_rows", lambda table, columns, limit=3: {"rows": []})
    monkeypatch.setattr("app.agent.narrow_llm_agent.lookup_geography", lambda query: {"resolved": True, "name": "California", "type": "state", "state_fips": "06"})
    monkeypatch.setattr(
        "app.agent.narrow_llm_agent.execute_sql",
        lambda sql, parameters=None: QueryResult(rows=[{"TOTAL_POPULATION": 39538223}], columns=["TOTAL_POPULATION"], query_id="q1"),
    )

    response = NarrowLLMCensusAgent(llm=llm).answer("What is the population of California?", "flow-test")

    assert response.status == "success"
    assert response.answer.startswith("California had")
    assert response.interpretation["llm_attempted"] is True
    assert response.interpretation["metadata_request"]["query"] == "total population"
    assert "B01003e1" in response.sql


def test_normalizes_llm_sql_identifiers_for_snowflake():
    sql = """
SELECT SUM(B02001e1) AS total_population
FROM US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET.PUBLIC.2020_CBG_B02
WHERE LEFT(CENSUS_BLOCK_GROUP, 2) = %(state_fips)s
"""

    normalized = normalize_snowflake_identifiers(sql)

    assert '"B02001e1"' in normalized
    assert '"CENSUS_BLOCK_GROUP"' in normalized
    assert '"US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET"."PUBLIC"."2020_CBG_B02"' in normalized


def test_llm_rate_limit_falls_back_to_metadata_sql(monkeypatch):
    monkeypatch.setattr(
        "app.agent.narrow_llm_agent.search_metadata",
        lambda query, top_k=30: {
            "results": [
                {
                    "table_name": "2020_CBG_B01",
                    "column_name": "B01003e1",
                    "label": "Estimate: TOTAL POPULATION: Total population: Total",
                    "universe": "Total population",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "app.agent.narrow_llm_agent.describe_table",
        lambda table: {
            "table_name": table,
            "columns": [
                {"column_name": "CENSUS_BLOCK_GROUP", "label": "Census Block Group identifier"},
                {"column_name": "B01003e1", "label": "Estimate: TOTAL POPULATION: Total population: Total"},
            ],
        },
    )
    monkeypatch.setattr("app.agent.narrow_llm_agent.lookup_geography", lambda query: {"resolved": True, "name": "United States", "type": "country"})
    monkeypatch.setattr(
        "app.agent.narrow_llm_agent.execute_sql",
        lambda sql, parameters=None: QueryResult(rows=[{"B01003E1": 331449281}], columns=["B01003E1"], query_id="q-rate-limit"),
    )

    response = NarrowLLMCensusAgent(llm=FailingLLM()).answer("What is the US population?", "rate-limit-fallback")

    assert response.status == "success"
    assert "331,449,281" in response.answer
    assert response.interpretation["scope_decision"]["llm_scope_fallback"] is True
    assert response.interpretation["sql_payload"]["fallback"] is True
    assert 'SUM("B01003e1")' in response.sql


def test_llm_rate_limit_falls_back_to_land_per_person_by_state(monkeypatch):
    def fake_search_metadata(query, top_k=30):
        rows = []
        if "land" in query.lower() or "area" in query.lower():
            rows.append(
                {
                    "table_name": "2020_METADATA_CBG_GEOGRAPHIC_DATA",
                    "column_name": "AMOUNT_LAND",
                    "label": "Land area",
                    "universe": "Census Block Groups",
                }
            )
        if "population" in query.lower():
            rows.append(
                {
                    "table_name": "2020_CBG_B01",
                    "column_name": "B01003e1",
                    "label": "Estimate: TOTAL POPULATION: Total population: Total",
                    "universe": "Total population",
                }
            )
        return {"results": rows}

    monkeypatch.setattr("app.agent.narrow_llm_agent.search_metadata", fake_search_metadata)
    monkeypatch.setattr(
        "app.agent.narrow_llm_agent.describe_table",
        lambda table: {
            "table_name": table,
            "columns": [
                {"column_name": "CENSUS_BLOCK_GROUP", "label": "Census Block Group identifier"},
                {"column_name": "AMOUNT_LAND", "label": "Land area"},
                {"column_name": "B01003e1", "label": "Estimate: TOTAL POPULATION: Total population: Total"},
            ],
        },
    )
    monkeypatch.setattr("app.agent.narrow_llm_agent.lookup_geography", lambda query: {"resolved": True, "name": "United States", "type": "country"})
    monkeypatch.setattr(
        "app.agent.narrow_llm_agent.execute_sql",
        lambda sql, parameters=None: QueryResult(rows=[{"STATE_FIPS": "02", "TOTAL_LAND_AREA": 1000, "TOTAL_POPULATION": 10, "LAND_PER_PERSON": 100}], columns=[], query_id="q-land-person"),
    )

    response = NarrowLLMCensusAgent(llm=FailingLLM()).answer("give me land per person in every state of usa", "land-person-fallback")

    assert response.status == "success"
    assert "land_per_person" in response.sql
    assert 'SUM("AMOUNT_LAND")' in response.sql
    assert 'SUM("B01003e1")' in response.sql
    assert "JOIN population" in response.sql


def test_llm_rate_limit_falls_back_to_top_states_by_land(monkeypatch):
    monkeypatch.setattr(
        "app.agent.narrow_llm_agent.search_metadata",
        lambda query, top_k=30: {
            "results": [
                {
                    "table_name": "2020_METADATA_CBG_GEOGRAPHIC_DATA",
                    "column_name": "AMOUNT_LAND",
                    "label": "Land area",
                    "universe": "Census Block Groups",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "app.agent.narrow_llm_agent.describe_table",
        lambda table: {
            "table_name": table,
            "columns": [
                {"column_name": "CENSUS_BLOCK_GROUP", "label": "Census Block Group identifier"},
                {"column_name": "AMOUNT_LAND", "label": "Land area"},
            ],
        },
    )
    monkeypatch.setattr("app.agent.narrow_llm_agent.lookup_geography", lambda query: {"resolved": False})
    monkeypatch.setattr(
        "app.agent.narrow_llm_agent.execute_sql",
        lambda sql, parameters=None: QueryResult(rows=[{"STATE_FIPS": "02", "TOTAL_LAND_AREA": 1000}], columns=[], query_id="q-land-top"),
    )

    response = NarrowLLMCensusAgent(llm=FailingLLM()).answer("top 10 states by land volume", "land-top-fallback")

    assert response.status == "success"
    assert 'SUM("AMOUNT_LAND")' in response.sql
    assert "GROUP BY state_fips" in response.sql
    assert "LIMIT 10" in response.sql
