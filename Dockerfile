FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8501
ENV USE_LLM=true
ENV LLM_BASE_URL=https://api.groq.com/openai/v1
ENV LLM_MODEL=openai/gpt-oss-120b
ENV QUERY_TIMEOUT_SECONDS=30
ENV SNOWFLAKE_DATABASE=US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET
ENV SNOWFLAKE_SCHEMA=PUBLIC

CMD ["streamlit", "run", "frontend/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501"]
