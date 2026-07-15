# US Census Data Assistant

Interactive chat agent for answering natural-language questions grounded in the Snowflake Marketplace US Open Census dataset.

The central design choice is that the LLM is used for language understanding and response wording, while metric definitions, geography mappings, SQL templates, permissions, and validation rules are controlled deterministically by the application.

## Architecture

Request flow:

1. Conversation context resolver expands follow-ups like "What about Texas?" or "What about NYC?"
2. Geography/entity resolver recognizes states plus verified city/county-set aliases such as NYC.
3. Input scope guardrail rejects off-topic requests after context resolution.
4. Intent parser extracts metric, geography level, selected entities, operation, limit, rank, thresholds, and breakdown dimension, with an optional hosted OpenAI-compatible LLM adapter as a fallback.
5. Semantic catalog maps user language to verified direct, composite, derived-rate, median, and distribution metrics.
6. Query planner builds a small, explicit plan.
7. SQL templates generate read-only Snowflake SQL.
8. SQL validator checks database, table, column, statement, and operation safety.
9. Snowflake executor runs the query with a timeout and query tag.
10. Result validator catches empty, null, negative, and implausible results.
11. Response generator returns a grounded answer plus interpretation and SQL.

## Local Setup

Install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in Snowflake credentials. The app has no demo-data mode; successful answers come from the configured Snowflake Census database. The required database is:

```text
US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET
```

Run the Streamlit app:

```bash
streamlit run frontend/streamlit_app.py
```

Run the API instead:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Public Deployment

The app does not depend on local Ollama or any local model endpoint. `USE_LLM=false` is the default, so deployed environments use the deterministic catalog parser. To add a hosted reachable LLM, set `USE_LLM=true` plus an OpenAI-compatible `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` from a provider with a free tier.

Public deployment files are included:

- `render.yaml`
- `Procfile`
- `runtime.txt`
- `.streamlit/config.toml`

See `docs/deployment.md` for Render and Streamlit Cloud setup. Snowflake credentials are required in deployment because the app intentionally does not ship bundled demo values.

## Data Discovery

Inspect Snowflake metadata:

```bash
python scripts/inspect_database.py
python scripts/build_catalog.py
python scripts/validate_metrics.py
```

`metadata/verified_metrics.json` contains the curated metric registry. Important verified mappings include:

```text
total_population -> 2020_CBG_B01.B01003e1
population_65_plus -> SUM(B01001 age 65+ columns)
population_by_age -> multiple B01001 age-band expressions
```

The app does not let the LLM choose substitute population universes such as veteran, adult, or civilian-only population columns.

Additional catalog artifacts:

- `metadata/taxonomy.json` describes Census topic categories.
- `metadata/variable_catalog.json` stores example variable-level metadata and is the hook for full metadata ingestion.
- `metadata/geographies.json` stores verified non-state geography aliases such as New York City.

## Supported Question Families

The planner distinguishes missing geography from analytical scope. A missing named state is valid when the user is asking the agent to identify states.

Examples:

- `Which state has higher population in USA?` -> ranking all states, limit 1.
- `What is second?` -> rank 2 using the previous ranking context.
- `Show me top 5.` -> top 5 using the previous metric and geography level.
- `Which states have more than 10 million people?` -> state-level threshold filter.
- `Break California down by age.` -> age-band population breakdown using verified B01001 age variables.
- `What about NYC?` -> inherits the previous metric and resolves NYC to the five borough county FIPS set.
- `Which state has more no. of people greater than 65 age?` -> ranks states by the composite `population_65_plus` metric.
- `Which state has the highest income?` -> asks for clarification instead of guessing an income definition.
- `Which state will have the highest population in 2040?` -> refused because the catalog contains historical data, not forecasts.

## Testing

Run:

```bash
pytest
python scripts/run_golden_tests.py
```

The current tests cover:

- State FIPS normalization.
- Input guardrails.
- Verified metric selection.
- Non-additive metric refusal.
- SQL safety validation.
- Ranking without a named geography.
- Ranking follow-ups such as second place and top N.
- Threshold filters.
- Age breakdown planning.
- Composite metric expressions such as population age 65+.
- Derived-rate metrics such as poverty, broadband access, and bachelor's-degree attainment.
- The full requested evaluator question set in `tests/golden/test_requested_question_set.py`. The planner portion runs locally; the answer-quality portion runs against Snowflake when credentials are configured.
- NYC alias/county-set resolution.
- Ambiguous income clarification.
- Forecast refusal.
- Golden question interpretation.

## Deployment

Deploy the Streamlit app or Docker image to a public host and set these environment variables:

- `USE_LLM` (`false` by default)
- `LLM_BASE_URL` (optional hosted OpenAI-compatible endpoint)
- `LLM_API_KEY` (optional, depending on provider)
- `LLM_MODEL` (optional hosted model name)
- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_USER`
- `SNOWFLAKE_PASSWORD`
- `SNOWFLAKE_ROLE`
- `SNOWFLAKE_WAREHOUSE`
- `SNOWFLAKE_DATABASE`
- `SNOWFLAKE_SCHEMA`

For production, use a read-only Snowflake role, a small dedicated warehouse, deployment secrets, and a hosted LLM endpoint only if you want LLM-assisted parsing beyond the deterministic catalog parser.

## Known Limits

This implementation intentionally supports a focused set of verified metrics first. Median household income uses a representative median aggregate template instead of summing block-group medians; derived rates use numerator and denominator formulas instead of averaging percentages.

Next improvements would include automatic table-grain discovery, county and tract geographies, duplicate-grain preflight checks, more verified metrics, and deployed end-to-end latency tests against the final hosting environment.
