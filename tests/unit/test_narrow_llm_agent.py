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


def test_narrow_agent_requires_llm():
    response = NarrowLLMCensusAgent(llm=None).answer("What is the US population?", "no-llm-test")

    assert response.status == "llm_unavailable"


def test_narrow_agent_rejects_out_of_scope_from_llm():
    llm = QueueLLM(
        [
            {
                "in_scope": False,
                "resolved_question": "What is the median income in Texas?",
                "reason": "Income is outside the supported scope.",
            }
        ]
    )

    response = NarrowLLMCensusAgent(llm=llm).answer("What is the median income in Texas?", "scope-test")

    assert response.status == "out_of_scope"
    assert "population, age, sex, race" in response.answer
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
