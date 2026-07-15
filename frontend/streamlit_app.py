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

st.markdown(
    """
    <style>
    :root {
        --snow-blue: #29B5E8;
        --deep-blue: #0B1F33;
        --mid-blue: #155E8A;
        --ice: #F7FBFF;
        --line: #D7EAF6;
        --muted: #5D7184;
    }

    .stApp {
        background:
            linear-gradient(180deg, #F7FBFF 0%, #FFFFFF 34%, #F4FAFE 100%);
        color: var(--deep-blue);
    }

    .block-container {
        max-width: 1180px;
        padding-top: 1.4rem;
        padding-bottom: 5rem;
    }

    [data-testid="stSidebar"] {
        background: #FFFFFF;
        border-right: 1px solid var(--line);
    }

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        color: var(--muted);
        font-size: 0.92rem;
    }

    .snow-header {
        border: 1px solid var(--line);
        background: #FFFFFF;
        border-radius: 8px;
        padding: 1.15rem 1.25rem;
        margin-bottom: 1rem;
        box-shadow: 0 16px 40px rgba(11, 31, 51, 0.06);
    }

    .snow-brand {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 0.55rem;
    }

    .snow-mark {
        width: 38px;
        height: 38px;
        border-radius: 8px;
        display: grid;
        place-items: center;
        color: #FFFFFF;
        background: var(--snow-blue);
        font-weight: 800;
        font-size: 1.25rem;
        box-shadow: 0 10px 24px rgba(41, 181, 232, 0.30);
    }

    .snow-title {
        margin: 0;
        color: var(--deep-blue);
        font-size: 1.7rem;
        line-height: 1.15;
        letter-spacing: 0;
        font-weight: 750;
    }

    .snow-subtitle {
        color: var(--muted);
        margin: 0;
        font-size: 0.98rem;
    }

    .status-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.65rem;
        margin-top: 1rem;
    }

    .status-pill {
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #F7FBFF;
        padding: 0.7rem 0.8rem;
    }

    .status-label {
        color: var(--muted);
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.2rem;
    }

    .status-value {
        color: var(--deep-blue);
        font-size: 0.92rem;
        font-weight: 700;
        overflow-wrap: anywhere;
    }

    .sidebar-title {
        color: var(--deep-blue);
        font-size: 0.9rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin: 0.25rem 0 0.6rem 0;
    }

    .sidebar-card {
        border: 1px solid var(--line);
        background: #F7FBFF;
        border-radius: 8px;
        padding: 0.85rem;
        margin-bottom: 1rem;
    }

    .sidebar-card strong {
        color: var(--deep-blue);
    }

    div.stButton > button {
        border-radius: 8px;
        border: 1px solid var(--line);
        background: #FFFFFF;
        color: var(--deep-blue);
        min-height: 2.5rem;
        font-weight: 650;
        text-align: left;
        transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
    }

    div.stButton > button:hover {
        border-color: var(--snow-blue);
        color: var(--mid-blue);
        box-shadow: 0 10px 24px rgba(41, 181, 232, 0.14);
        transform: translateY(-1px);
    }

    [data-testid="stChatMessage"] {
        border: 1px solid var(--line);
        background: #FFFFFF;
        border-radius: 8px;
        box-shadow: 0 10px 30px rgba(11, 31, 51, 0.045);
        margin-bottom: 0.85rem;
    }

    [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {
        color: var(--deep-blue);
    }

    [data-testid="stChatInput"] {
        border-top: 1px solid var(--line);
        background: rgba(247, 251, 255, 0.92);
        backdrop-filter: blur(8px);
    }

    [data-testid="stExpander"] {
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #FBFDFF;
    }

    pre {
        border-radius: 8px !important;
        border: 1px solid #CFE8F7;
    }

    @media (max-width: 760px) {
        .status-grid {
            grid-template-columns: 1fr;
        }

        .snow-title {
            font-size: 1.35rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "agent" not in st.session_state:
    st.session_state.agent = CensusChatAgent()

llm_status = settings.llm_model if settings.has_hosted_llm_config else "Not configured"
snowflake_status = "Connected" if settings.has_snowflake_credentials else "Not configured"

st.markdown(
    f"""
    <section class="snow-header">
        <div class="snow-brand">
            <div class="snow-mark">SF</div>
            <div>
                <h1 class="snow-title">{settings.app_name}</h1>
                <p class="snow-subtitle">Snowflake-backed Census analytics for population, age, sex, race, and geography.</p>
            </div>
        </div>
        <div class="status-grid">
            <div class="status-pill">
                <div class="status-label">Warehouse</div>
                <div class="status-value">Snowflake {snowflake_status}</div>
            </div>
            <div class="status-pill">
                <div class="status-label">Planner</div>
                <div class="status-value">{llm_status}</div>
            </div>
            <div class="status-pill">
                <div class="status-label">Scope</div>
                <div class="status-value">Census B01, B02, land/geography</div>
            </div>
        </div>
    </section>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown('<div class="sidebar-title">Runtime</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="sidebar-card">
            <strong>Planning</strong><br>
            Hosted LLM scope, metadata selection, SQL generation, and answer drafting.
        </div>
        <div class="sidebar-card">
            <strong>Data Boundary</strong><br>
            Population, age, sex, race, land, and Census geography only.
        </div>
        """,
        unsafe_allow_html=True,
    )
    if settings.has_hosted_llm_config:
        st.success(f"Hosted LLM: {settings.llm_model}")
    elif settings.use_llm:
        st.warning("USE_LLM is true, but LLM_BASE_URL, LLM_MODEL, and LLM_API_KEY are not fully configured.")
    if settings.has_snowflake_credentials:
        st.success("Snowflake: configured")
    else:
        st.warning("Snowflake: not configured")
    st.markdown('<div class="sidebar-title">Try</div>', unsafe_allow_html=True)
    examples = [
        "What is the US population?",
        "What is the population of California?",
        "Which state has the highest population?",
        "How many people are over 65 in the US?",
        "Are there more males or females in Texas?",
        "What is the racial distribution of Georgia?",
        "Which state has the largest land area?",
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
        if message.get("evidence"):
            with st.expander("Evidence"):
                st.json(message["evidence"])
        if message.get("sql"):
            with st.expander("SQL"):
                st.code(message["sql"], language="sql")

question = st.chat_input("Ask about US Census population, age, sex, race, land, or geography")
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
        if response.evidence:
            with st.expander("Evidence"):
                st.json(response.evidence)
        if response.sql:
            with st.expander("SQL"):
                st.code(response.sql, language="sql")

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": response.answer,
            "interpretation": response.interpretation,
            "evidence": response.evidence,
            "sql": response.sql,
        }
    )
