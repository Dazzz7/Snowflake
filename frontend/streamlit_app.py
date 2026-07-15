from __future__ import annotations

import sys
import uuid
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent.orchestrator import CensusChatAgent
from app.config import settings


st.set_page_config(page_title=settings.app_name, layout="wide")

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "agent" not in st.session_state:
    st.session_state.agent = CensusChatAgent()

st.title(settings.app_name)

with st.sidebar:
    st.subheader("Status")
    st.write("Language parsing: deterministic catalog parser")
    if settings.has_hosted_llm_config:
        st.write(f"Hosted LLM: `{settings.llm_model}`")
    elif settings.use_llm:
        st.warning("USE_LLM is true, but LLM_BASE_URL, LLM_MODEL, and LLM_API_KEY are not fully configured.")
    st.write("Snowflake: configured" if settings.has_snowflake_credentials else "Snowflake: not configured")
    st.subheader("Try")
    examples = [
        "What is the total population of California?",
        "Compare the populations of Texas and Florida",
        "Top 10 states by population",
        "What about New York?",
    ]
    for example in examples:
        if st.button(example, use_container_width=True):
            st.session_state.pending_question = example

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("interpretation"):
            with st.expander("How I interpreted this"):
                st.json(message["interpretation"])
        if message.get("sql"):
            with st.expander("SQL"):
                st.code(message["sql"], language="sql")

question = st.chat_input("Ask a question about US Census population and demographics")
if not question and st.session_state.get("pending_question"):
    question = st.session_state.pop("pending_question")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Checking the catalog and querying Census data..."):
            response = st.session_state.agent.answer(question, st.session_state.session_id)
        st.markdown(response.answer)
        if response.interpretation:
            with st.expander("How I interpreted this"):
                st.json(response.interpretation)
        if response.sql:
            with st.expander("SQL"):
                st.code(response.sql, language="sql")

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": response.answer,
            "interpretation": response.interpretation,
            "sql": response.sql,
        }
    )
