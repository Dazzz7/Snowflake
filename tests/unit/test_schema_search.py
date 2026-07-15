from app.catalog.catalog_search import rank_schema_rows, schema_search_terms, summarize_schema_matches


def test_schema_search_terms_remove_generic_words():
    terms = schema_search_terms("What fields do you have about shopping brands and distance?")

    assert "fields" not in terms
    assert "shopping" in terms
    assert "brands" in terms
    assert "distance" in terms


def test_rank_schema_rows_prioritizes_matching_columns():
    rows = [
        {"TABLE_NAME": "2020_CBG_B01", "COLUMN_NAME": "B01003e1", "DATA_TYPE": "NUMBER", "COMMENT": "Population"},
        {"TABLE_NAME": "2019_CBG_PATTERNS", "COLUMN_NAME": "TOP_BRANDS", "DATA_TYPE": "VARIANT", "COMMENT": None},
        {"TABLE_NAME": "2019_CBG_PATTERNS", "COLUMN_NAME": "DISTANCE_FROM_HOME", "DATA_TYPE": "NUMBER", "COMMENT": None},
    ]

    ranked = rank_schema_rows("shopping brands distance", rows, limit=2)
    summary = summarize_schema_matches(ranked)

    assert {item["column"] for item in summary} == {"DISTANCE_FROM_HOME", "TOP_BRANDS"}
