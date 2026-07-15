# Public Deployment

Live app: https://us-census-data-assistant.onrender.com

The app has no demo-data mode and no local-model dependency. Public deployments must be configured with Snowflake credentials and a Gemini API key. Gemini is used through Google's OpenAI-compatible Gemini API endpoint.

## Render

This repo includes `render.yaml`.

1. Push the repository to GitHub.
2. In Render, create a new Blueprint from the repository.
3. Set the required Snowflake variables as Render secrets/environment variables:

```text
USE_LLM=true
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
LLM_API_KEY=...
LLM_MODEL=gemini-3.5-flash
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

4. Get the Gemini key from Google AI Studio and store it as `LLM_API_KEY` in the deployment environment, never in git.

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
