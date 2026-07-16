# US Census Data Assistant

Interactive chat agent for answering natural-language questions grounded in the Snowflake Marketplace US Open Census dataset.

Live app: https://us-census-data-assistant.onrender.com

Video: https://drive.google.com/file/d/1TeupMBi6Lb7Zv2bXHwQ8iGQgnkFqxHaM/view?usp=drive_link

The central design choice is that Groq-hosted GPT-OSS is used for scope detection, metadata selection, SQL planning, and answer generation, while the application constrains the model to approved Census tables, validates SQL, executes only against Snowflake, and exposes the evidence back to the user.

## Architecture

Request flow:

1. Streamlit receives the user's natural-language Census question.
2. The agent loads session context for short follow-ups.
3. The LLM decides whether the question is plausibly related to the available Snowflake Census dataset.
4. The LLM requests relevant metadata and candidate tables.
5. The app retrieves metadata from Snowflake and compactly describes approved tables.
6. The app resolves geography such as California or Texas to verified FIPS filters.
7. The LLM generates one read-only Snowflake SQL query.
8. If the hosted LLM is rate-limited or returns empty SQL, the app can build a conservative fallback query from the retrieved metadata for common aggregate, threshold, land, and per-person requests.
9. The app normalizes Snowflake identifiers, validates the SQL, and blocks unsafe or out-of-scope queries.
10. Snowflake executes the query with a timeout and query tag.
11. The LLM generates the final answer only from returned Snowflake rows; if that fails, the app renders a deterministic row-based answer.
12. The UI shows the answer, interpretation, evidence, and SQL.

## Local Setup

Install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in Snowflake credentials plus `LLM_API_KEY` from Groq. The app has no demo-data mode; successful answers come from the configured Snowflake Census database. The required database is:

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

The app does not depend on local Ollama or any local model endpoint. Public deployment uses Groq's OpenAI-compatible API:

```text
USE_LLM=true
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-120b
LLM_API_KEY=<Groq API key>
```

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

The current runtime does not send the entire Snowflake schema to the LLM. Instead, it searches Census variable metadata for the user's question, retrieves a compact set of candidate fields, and uses those retrieved tables and columns as the temporary SQL allowlist for that request.

For example, a question about rental units retrieves renter-occupied housing-unit metadata such as tenure variables, while a population question retrieves population variables. The LLM writes SQL only from the metadata candidate set supplied by the application.

The app also has metadata-derived fallback planning for simple cases when the hosted LLM is rate-limited. Examples include:

- `What is the US population?` -> retrieve total-population metadata and sum the selected estimate.
- `Which Census Block Groups have over 100 rental units?` -> retrieve renter-occupied housing-unit metadata and apply a threshold.
- `top 10 states by land volume` -> retrieve `AMOUNT_LAND`, aggregate by state FIPS, and rank descending.
- `give me land per person in every state of usa` -> retrieve land metadata plus total-population metadata and compute `SUM(AMOUNT_LAND) / SUM(total population)` by state.

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
- `Which Census Block Groups have over 100 rental units?` -> retrieves renter-occupied housing-unit metadata and queries matching block groups.
- `Which state has the highest median household income?` -> retrieves income metadata and lets SQL validation enforce the retrieved candidate fields.
- `top 10 states by land volume` -> aggregates land area by state.
- `give me land per person in every state of usa` -> combines land area and population metadata to compute a derived per-person measure.
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
- SQL safety validation.
- Narrow LLM agent flow.
- Out-of-scope refusals.
- Snowflake identifier normalization.
- Metadata search helpers.
- Metadata-derived fallback SQL for provider rate limits.
- Land-area and land-per-person fallback queries.
- Geography lookup and enrichment.
- Public-mode hosted LLM configuration.
- Golden question behavior where Snowflake and hosted LLM credentials are available.

## Written Reflection

### Development Process and Key Architectural Decisions

I started by building a curated metric assistant, then tried a very broad LLM-driven version. The broad version was flexible, but it could hallucinate columns or use the wrong Census universe. The final design keeps broad Census coverage while avoiding full-schema prompting: the app retrieves only question-relevant metadata from Snowflake and turns that retrieved candidate set into the SQL allowlist for that request.

The main architecture decision was to let the LLM do language-heavy work while the application controls the data boundary. Groq-hosted `openai/gpt-oss-120b` handles scope detection, metadata search planning, SQL generation, and answer generation when available. The app retrieves Snowflake metadata, restricts SQL to the retrieved tables and columns, normalizes Snowflake identifiers, validates SQL, executes the query, and shows the evidence and SQL in the UI. For common aggregate and derived questions, the app can also build conservative SQL from retrieved metadata when the LLM is rate-limited.

I also removed demo-data mode so the public app only answers from Snowflake. The frontend is Streamlit for speed and transparency, hosted publicly on Render, with a Snowflake-inspired interface so reviewers can immediately see the product direction.

### What I Would Improve With More Time

I would add a durable session store such as Redis or Postgres instead of process-local memory. I would also add a stronger SQL AST validator, richer observability, query cost estimation, and an audit log that records every question, model response, SQL query, Snowflake query ID, and user feedback.

The next data improvement would be to make the metadata retrieval layer more semantic, with embeddings or a precomputed search index over Census labels, universes, and topics. I would also add a metadata browsing view so users can see what the assistant can answer before asking.

### Edge Cases and Failure Modes

Key failure modes identified include LLM rate limits, malformed JSON from the model, oversized metadata prompts, Snowflake quoting errors, missing or ambiguous geography, unsupported future-looking questions, and user requests outside the Census dataset. The app handles many of these with retries, compacted metadata, identifier normalization, SQL validation, timeouts, refusal paths, and metadata-derived fallback SQL for common questions.

Some edge cases are not fully solved yet. Multi-worker deployments would lose conversation context because memory is local to the process. Very complex geography requests, joins across new Census domains, and questions requiring non-additive statistics need stronger semantic contracts before they should be supported.

### Testing Approach and Future Test Additions

The test suite focuses on the parts most likely to cause incorrect answers: scope handling, geography resolution, SQL safety, identifier normalization, metadata helpers, metadata ranking, fallback SQL generation, and the LLM-agent flow. I also ran live smoke tests against Groq and Snowflake for population, housing/rental-unit metadata, land-area ranking, land-per-person calculations, and out-of-scope/rate-limit behavior.

With more time, I would add deployed end-to-end tests that run against the public Render app, latency tests for the 60-second requirement, failure-injection tests for Snowflake and Groq outages, more adversarial prompt-injection cases, and a larger golden set covering follow-up questions and geography variations.

## Deployment

Deploy the Streamlit app or Docker image to a public host and set these environment variables:

- `USE_LLM` (`true` for public deployment)
- `LLM_BASE_URL` (`https://api.groq.com/openai/v1`)
- `LLM_API_KEY` (Groq API key)
- `LLM_MODEL` (`openai/gpt-oss-120b`)
- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_USER`
- `SNOWFLAKE_PASSWORD`
- `SNOWFLAKE_ROLE`
- `SNOWFLAKE_WAREHOUSE`
- `SNOWFLAKE_DATABASE`
- `SNOWFLAKE_SCHEMA`

For production, use a read-only Snowflake role, a small dedicated warehouse, deployment secrets, and the Groq API key as a deployment secret.

## Known Limits

This implementation retrieves question-specific Census metadata instead of sending the whole schema to the LLM. The main limitation is that lexical metadata search can still miss the best field or rank a related field too highly, so production should use stronger semantic search, more metadata reranking rules, and SQL AST validation. Fallback answers are intentionally conservative and can be more utilitarian than LLM-written responses.

Next improvements would include automatic table-grain discovery, county and tract geographies, duplicate-grain preflight checks, semantic metadata embeddings, and deployed end-to-end latency tests against the final hosting environment.
