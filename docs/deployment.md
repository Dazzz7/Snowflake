# Public Deployment

Live app: https://us-census-data-assistant.onrender.com

The app has no demo-data mode and no local-model dependency. Public deployments must be configured with Snowflake credentials and a Groq API key. Groq is used through its OpenAI-compatible API endpoint.

## Render

This repo includes `render.yaml`.

1. Push the repository to GitHub.
2. In Render, create a new Blueprint from the repository.
3. Set the required Snowflake variables as Render secrets/environment variables:

```text
USE_LLM=true
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=...
LLM_MODEL=openai/gpt-oss-120b
LLM_TIMEOUT_SECONDS=20
QUERY_TIMEOUT_SECONDS=30
SNOWFLAKE_ACCOUNT=...
SNOWFLAKE_USER=...
SNOWFLAKE_PASSWORD=...
SNOWFLAKE_ROLE=...
SNOWFLAKE_WAREHOUSE=...
SNOWFLAKE_DATABASE=US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET
SNOWFLAKE_SCHEMA=PUBLIC
```

4. Store the Groq key as `LLM_API_KEY` in the deployment environment, never in git.

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
