# Public Deployment

The app has no demo-data mode and no local-model dependency. Public deployments must be configured with Snowflake credentials. `USE_LLM=false` is the default, so the deterministic catalog parser works without any LLM service.

## Render

This repo includes `render.yaml`.

1. Push the repository to GitHub.
2. In Render, create a new Blueprint from the repository.
3. Set the required Snowflake variables as Render secrets/environment variables:

```text
USE_LLM=false
QUERY_TIMEOUT_SECONDS=30
SNOWFLAKE_ACCOUNT=...
SNOWFLAKE_USER=...
SNOWFLAKE_PASSWORD=...
SNOWFLAKE_ROLE=...
SNOWFLAKE_WAREHOUSE=...
SNOWFLAKE_DATABASE=US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET
SNOWFLAKE_SCHEMA=PUBLIC
```

4. Optional hosted LLM parsing:

```text
USE_LLM=true
LLM_BASE_URL=https://your-openai-compatible-provider.example/v1
LLM_API_KEY=...
LLM_MODEL=...
LLM_TIMEOUT_SECONDS=20
```

## Streamlit Community Cloud

Use:

```text
frontend/streamlit_app.py
```

as the app entrypoint. Add the same variables above as Streamlit secrets or environment variables.

## Required Verification

After deployment, run the requested-question set manually from the public URL and run the Snowflake integration test locally or in CI with the same secrets:

```bash
pytest tests/golden/test_requested_question_set.py
```
