# Candidate Assignment Evaluation

## 1. Executive Summary

Overall score: **62/100**

Recommendation: **Do not advance / do not submit yet**

This repository now has a real Snowflake-backed path, no demo-data fallback, and Gemini deployment configuration through Google's OpenAI-compatible Gemini API. The requested evaluator question set passed against live Snowflake during this audit. However, it still fails the public-deployment non-negotiable until a live URL is available, and the Gemini production path remains unverified until the host has `LLM_API_KEY` set and a live Gemini trace is captured.

Top strengths:
1. Every successful Census answer in the current code path goes through SQL generation, SQL validation, Snowflake execution, result validation, and response generation. Evidence: `app/agent/orchestrator.py:77-122`.
2. Demo-data mode and local Ollama paths are absent. Evidence: `rg -n "demo_data_mode|DEMO_DATA_MODE|__DEMO__|OLLAMA|localhost:11434|ollama_client|OllamaClient"` returned no matches in app/docs/tests/deploy files.
3. Live Snowflake integration passed the requested question set. Evidence: `pytest` output: `22 passed`, including `tests/golden/test_requested_question_set.py::test_requested_question_set_answers_from_snowflake`.

Critical weaknesses:
1. No public URL is present or verified. `docs/deployment.md:9-11` describes how to deploy, but no live deployment evidence exists.
2. Gemini is configured in deployment files but not yet verified through a public deployment. Evidence: `render.yaml` sets `USE_LLM=true`, `LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai`, and `LLM_MODEL=gemini-3.5-flash`; `LLM_API_KEY` is a required secret.
3. The dataset/metadata coverage is curated, not complete schema-aware reasoning. Evidence: `metadata/verified_metrics.json` is a manually maintained registry; `app/catalog/metric_registry.py:17-23` loads local JSON.

## 2. Executive Truth Check

| Question | Status | Evidence | Limitations | Confidence |
|---|---|---|---|---|
| Publicly reachable deployed app? | FAIL | No URL in README or docs; `docs/deployment.md:9-11` only gives future deployment steps. | No deployed browser test possible. | High |
| Evaluator can use without local setup? | FAIL | README requires local setup and Snowflake env vars: `README.md:23-43`, `README.md:136-148`. | Could pass after deployment, but not evidenced. | High |
| Connects to required Census dataset in Snowflake? | PASS | Runtime config printed `US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET`; executor uses Snowflake in `app/database/query_executor.py:19-33`. | Verified locally, not deployed. | High |
| Production uses a real LLM? | NOT TESTED | Render config now enables Gemini, and `IntentParser` instantiates an LLM only when `LLM_API_KEY` is configured: `app/agent/intent_parser.py:27-29`, `app/config.py:32-34`. | No public deployment trace proves Gemini succeeded yet. | High |
| Every factual Census answer requires real Snowflake query? | PASS | Orchestrator executes Snowflake before response: `app/agent/orchestrator.py:86-122`; no demo matches from rg. | Capability response is metadata, not a factual Census value. | High |
| Answers generated from returned Snowflake rows? | PASS | `ResponseGenerator.generate` reads `result.rows`: `app/agent/response_generator.py:37-162`. Sentinel probe changed answer from `987,654,321` to `123,456,789`. | Final wording is templated. | High |
| Can answer novel questions not present in source? | PARTIAL | Runtime novel query `Which Oregon counties have more than 100,000 residents?` returned Snowflake rows and SQL. | Only within curated metric/geography patterns; no real LLM needed/used. | Medium |
| Preserves context across turns? | PARTIAL | State model: `app/memory/conversation_state.py:8-57`; resolver handles second/top/NYC: `tests/unit/test_context_resolver.py:5-32`. | In-memory only; complex scenarios not fully supported. | High |
| Clarifies when necessary? | PASS | Income ambiguity in `app/agent/intent_parser.py:90-99`; test `tests/unit/test_query_pipeline.py:92-97`. | Limited to known ambiguity rules. | High |
| Rejects off-topic requests? | PARTIAL | Guardrail terms in `app/guardrails/input_guardrail.py:6-71`; runtime `Tell me a joke.` returned `out_of_scope`. | Keyword-based; many off-topic prompts may slip through. | High |
| Avoids hallucinating when data unavailable? | PARTIAL | Result errors suppress success: `app/agent/result_validator.py:9-12`, `orchestrator.py:95-108`. | Unknown geographies return generic clarification, not specific no-data. | Medium |
| Fails clearly if LLM unavailable? | PARTIAL | Missing Gemini config shows a Streamlit sidebar warning; malformed LLM returns `None`: `hosted_llm_client.py:47-63`. | Invalid Gemini key path still needs live failure-injection evidence. | Medium |
| Fails clearly if Snowflake unavailable? | PASS | Missing credentials probe returned `invalid_result` and no factual answer; code at `app/database/snowflake_client.py:14-19`. | Error message exposes env var names, not secret values. | High |
| SQL validated before execution? | PASS | `orchestrator.py:86-95` validates before executor. | Validator quality is partial; see SQL section. | High |
| Production mocks/fixtures disabled? | PASS | No demo/mock strings found by rg; executor is Snowflake-only: `app/database/query_executor.py:17-38`. | Tests still use direct fake result objects for unit-level assertions. | High |
| Responses normally under 60 seconds? | PASS locally / NOT TESTED deployed | 20-request local Snowflake sample: min 0ms, median 1154ms, p90 1672ms, p95 1813ms, max 2550ms. | Public deployment performance not measured. | Medium |
| Meaningful automated tests included? | PASS | `pytest`: 22 collected, 22 passed. Test files listed under `tests/`. | Coverage not measured. | High |
| README matches implementation? | PARTIAL | README says default deterministic parsing and no demo mode: `README.md:51-62`; also says central design uses LLM for language understanding at `README.md:5`, which overstates default behavior. | Needs live URL and clearer “LLM optional” wording at top. | High |
| Detailed reflection? | PASS | `docs/reflection.md:3-50`. | Could be more specific about deployed gaps. | High |
| Fake/scripted/incomplete production paths? | PARTIAL | SQL is generated from deterministic templates in `app/agent/sql_generator.py`; curated registry in `metadata/verified_metrics.json`. | No fixture data, but templates/curated subset are real limitations. | High |

## 3. Automatic Rejection Risks

| Risk | Status | Evidence |
|---|---|---|
| Production silently falls back to mock LLM | PASS | No mock LLM found; `IntentParser` uses `None` if hosted config missing: `app/agent/intent_parser.py:27-38`. |
| Production silently falls back to fixture data | PASS | No demo strings found; executor only uses `snowflake_connection`: `app/database/query_executor.py:19-33`. |
| Example questions receive canned answers | PARTIAL | Answers are templated, but values come from `result.rows`: `app/agent/response_generator.py:37-162`; sentinel test proved value dependency. |
| SQL selected from fixed templates based on keywords | PARTIAL | SQL generator is template-based: `app/agent/sql_generator.py:50-182`; planner is deterministic and metric registry based. |
| Final answer generated without Snowflake query | PASS for factual answers | `orchestrator.py:95-122` executes and validates results before response. Metadata/capability responses bypass Snowflake by design: `orchestrator.py:42-68`. |
| Invents answers after Snowflake errors | PASS | Missing Snowflake credentials returned `invalid_result`, no factual value. |
| README claims unimplemented features | PARTIAL | README now documents Gemini deployment config, but no live URL is present. |
| Public URL broken/missing | FAIL | No live URL in README/docs. |
| Secrets committed | PASS | Secret scan found only placeholders/references; `.gitignore` excludes `.env`. |
| Exceeds 60 seconds | NOT TESTED deployed | Local sample max 2550ms; no public deployment measurement. |
| Context only hard-coded examples | PARTIAL | Resolver uses hard-coded regex patterns: `app/agent/context_resolver.py`; tested cases are narrow. |
| Only small curated subset supported | FAIL/PARTIAL | Curated registry has selected metrics; `README.md:152-156` acknowledges focused set. |
| SQL can access unapproved objects | PARTIAL | Database string required by validator: `app/agent/sql_validator.py:40-41`, but AST/table validation is not complete. |
| Model can generate write operations | PASS | LLM cannot execute SQL; SQL validator blocks writes: `app/agent/sql_validator.py:10-35`. |
| Tests only fake paths | PARTIAL | Live Snowflake golden exists and passed: `tests/golden/test_requested_question_set.py:66-77`; many unit tests are planner-only. |

## 4. Scorecard

| Category | Score | Maximum |
|---|---:|---:|
| LLM and AI Engineering | 11 | 30 |
| Production Quality | 22 | 30 |
| Product and UI | 5 | 15 |
| Judgment | 14 | 15 |
| Reflection and Handoff | 10 | 10 |
| Total | 62 | 100 |

Critical cap note: until a deployed Gemini trace is captured, the LLM/AI Engineering section cannot receive full real-LLM credit.

## 5. Requirement-by-Requirement Results

| Requirement | Status | Evidence | Notes |
|---|---|---|---|
| Public web app | FAIL | No URL in docs; only deployment instructions in `docs/deployment.md:9-43`. | Largest blocker. |
| No local setup for evaluator | FAIL | `.env.example` requires Snowflake credentials: `.env.example:7-14`. | Could be fixed by deployed secrets. |
| Real LLM | NOT TESTED | Gemini env vars are configured in deployment files; test proves a configured hosted LLM object is attempted. | Needs deployed Gemini API trace with real key. |
| Multi-turn context | PARTIAL | `ConversationState` stores last metric/result: `app/memory/conversation_state.py:8-57`. | In-memory only. |
| Sub-60s responses | PASS locally | 20-request sample p95 1813ms, max 2550ms. | Deployed not tested. |
| Guardrails | PARTIAL | Keyword guardrail: `app/guardrails/input_guardrail.py:6-71`. | Not semantic. |
| Graceful degradation | PARTIAL | Snowflake errors suppress factual answers: `orchestrator.py:95-108`. | LLM unavailability silently disables optional fallback. |
| Meaningful tests | PASS | `pytest`: 22 passed. | No coverage, no live LLM test, no deployed E2E. |
| Complete dataset/schema awareness | FAIL | Uses curated local registry: `metadata/verified_metrics.json`; not complete metadata selection. | `schema_loader.py` can query `INFORMATION_SCHEMA`, but runtime planner does not use it. |
| Thoughtful reflection | PASS | `docs/reflection.md:3-50`. | Honest but should mention no public URL if not deployed. |

## 6. Production Request Trace

Local production-path trace, not deployed:

Question: `Which Oregon counties have more than 100,000 residents?`

Runtime output:

```text
STATUS: success
MS: 2652
ANSWER: Using the available 2020 Census dataset, these counties have more than 100,000 people: 41051 (809,869), 41067 (595,761), ...
TYPE: filter
SQL: SELECT LEFT("CENSUS_BLOCK_GROUP", 5) AS county_fips, SUM("B01003e1") AS value
FROM "US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET"."PUBLIC"."2020_CBG_B01"
WHERE LEFT("CENSUS_BLOCK_GROUP", 2) = %(parent_state_fips)s
GROUP BY 1
HAVING SUM("B01003e1") > %(threshold_value)s
ORDER BY value DESC
LIMIT 100
ROWS: [{'COUNTY_FIPS': '41051', 'VALUE': 809869.0}, {'COUNTY_FIPS': '41067', 'VALUE': 595761.0}]
```

Call graph:

```text
frontend/streamlit_app.py:51-62
-> CensusChatAgent.answer(question, session_id), app/agent/orchestrator.py:27
-> session_store.get, app/memory/session_store.py:10-13
-> resolve_context, app/agent/context_resolver.py
-> classify_input, app/guardrails/input_guardrail.py:65-71
-> IntentParser.parse, app/agent/intent_parser.py:31-45
-> QueryPlanner.create_plan, app/agent/query_planner.py:8-134
-> SQLGenerator.generate, app/agent/sql_generator.py:44-182
-> SQLValidator.validate, app/agent/sql_validator.py:26-68
-> SnowflakeQueryExecutor.execute, app/database/query_executor.py:17-38
-> ResultValidator.validate, app/agent/result_validator.py:7-30
-> ConversationState.remember, app/memory/conversation_state.py:23-57
-> ResponseGenerator.generate, app/agent/response_generator.py:37-162
-> Streamlit renders answer/sql, frontend/streamlit_app.py:63-69
```

LLM invoked in this local trace: **No**. The current code now attempts a configured hosted LLM and records telemetry, but this specific trace was captured before a Gemini key was configured locally.

Snowflake invoked: **Yes**. Evidence: returned rows and Snowflake SQL above; executor path at `app/database/query_executor.py:19-33`.

## 7. LLM Engineering Review

Status: **FAIL for production real LLM**

Evidence:
- Hosted LLM client exists and calls OpenAI-compatible `/chat/completions`: `app/agent/hosted_llm_client.py:12-45`.
- Parser only instantiates it if `settings.has_hosted_llm_config`: `app/agent/intent_parser.py:27-29`.
- `settings.has_hosted_llm_config` requires `USE_LLM`, `LLM_BASE_URL`, and `LLM_MODEL`: `app/config.py:32-34`.
- Render config sets `USE_LLM=true`, Gemini base URL, and `gemini-3.5-flash`; `LLM_API_KEY` is a host secret.
- Runtime probe printed:

```text
USE_LLM true in render.yaml
LLM_BASE_URL https://generativelanguage.googleapis.com/v1beta/openai
LLM_MODEL gemini-3.5-flash
LLM_API_KEY required as deployment secret
```

Malformed output behavior: `generate_json` returns `None` on no JSON or parse error: `app/agent/hosted_llm_client.py:47-63`. The parser then keeps deterministic output: `app/agent/intent_parser.py:37-45`.

No token usage, retry counts, model latency recording, or live LLM test evidence exists.

## 8. Snowflake and Data Grounding

Status: **PASS for queried metrics, PARTIAL for complete dataset awareness**

Evidence:
- Snowflake database default: `app/config.py:25-29`.
- Executor uses Snowflake connector and sets statement timeout: `app/database/query_executor.py:19-33`.
- Credential failure is explicit: `app/database/snowflake_client.py:14-19`.
- Local curated metrics include population, senior population, median income, poverty, uninsured, broadband, SNAP, education, race, age: `metadata/verified_metrics.json:2-260`.
- Metadata discovery helper queries `INFORMATION_SCHEMA.COLUMNS`: `app/database/schema_loader.py:7-20`.

Limitations:
- Runtime planner uses local curated JSON, not live schema retrieval: `app/catalog/metric_registry.py:17-23`.
- Complete usable dataset is not exposed; README acknowledges focused metrics: `README.md:152-156`.
- No live join discovery, comments retrieval in runtime selection, duplicate-grain preflight, or automatic year discovery.
- Puerto Rico handling is imperfect: live query for poverty returned `STATE_FIPS='72'`, and response said `72 has the highest poverty rate...` because state lookup does not label Puerto Rico.

## 9. SQL Safety Review

Status: **PARTIAL**

Evidence:
- Validation happens before execution: `app/agent/orchestrator.py:86-95`.
- Write keywords are blocked: `app/agent/sql_validator.py:10-35`.
- Multiple statements and wildcard selects are rejected: `app/agent/sql_validator.py:36-39`.
- Approved database string is required: `app/agent/sql_validator.py:40-41`.
- Required metric identifiers are checked: `app/agent/sql_validator.py:43-68`.

Validator probe results:

| Probe | Result | Reason |
|---|---|---|
| `DROP TABLE census_data` | Rejected | Only SELECT statements are allowed. |
| `SELECT * FROM allowed_table` | Rejected | Wildcard column selection is not allowed. |
| `DELETE FROM allowed_table` | Rejected | Only SELECT statements are allowed. |
| `SELECT * FROM secret_schema.users` | Rejected | Wildcard column selection is not allowed. |
| Approved SQL + `UNION ALL SELECT * FROM secret_schema.users` | Rejected | Wildcard column selection is not allowed. |
| Approved SQL + `CROSS JOIN another_table` | **Accepted** | No AST/table validation catches appended join. |
| Approved SQL + `LIMIT 100000000` | **Accepted** | No maximum LIMIT enforcement. |
| Approved SQL + `; -- DELETE...` | Rejected | Blocked keyword. |
| `WITH x AS (SELECT * FROM secret_schema.users) SELECT * FROM x` | Rejected | Wildcard column selection. |

The validator is regex/string based, not AST based. It needs stronger table/function/join/LIMIT validation before claiming production-grade SQL safety.

## 10. Conversation and Context Review

Status: **PARTIAL**

Evidence:
- In-memory state: `app/memory/session_store.py:6-16`.
- Stored fields include `last_metric`, `last_geography_level`, `last_result_set`: `app/memory/conversation_state.py:8-21`.
- Resolver handles known follow-up patterns: tests in `tests/unit/test_context_resolver.py:5-32`.
- Runtime follow-up after poverty ranking: `What is second?` produced `Mississippi ranks second...` with `LIMIT 1 OFFSET 1`.

Limitations:
- Context is process-local and disappears on restart.
- Complex scenarios from the evaluator prompt are not all supported. Example: “Compare those two,” “Use previous available year,” “Add Florida,” and “percentage difference” are not evidenced.
- Follow-up recognition is regex based.

## 11. Guardrails and Failure Handling

Status: **PARTIAL**

Runtime probes:

| Request | Status | Answer | LLM called | Snowflake called |
|---|---|---|---|---|
| `Tell me a joke.` | `out_of_scope` | Census-only refusal | No | No |
| `Give me data for the year 2050.` | `needs_clarification` | Asked for geography | No | No |
| `What is the population of Atlantis?` | `needs_clarification` | Asked for geography | No | No |
| Missing Snowflake credentials | `invalid_result` | Explicit credential config message | No | Attempted, stopped before connection |

Evidence:
- Guardrail keyword lists: `app/guardrails/input_guardrail.py:6-56`.
- Out-of-scope response: `app/agent/orchestrator.py:69-75`.
- Result errors suppress success: `app/agent/result_validator.py:9-12`, `app/agent/orchestrator.py:95-108`.

Limitations:
- Guardrails are keyword based, not model/classifier based.
- Future-year handling only works after a metric is parsed; generic “data for 2050” asks for geography instead of saying unsupported future year.
- Not all failure injections were run: invalid LLM key, LLM timeout, malformed LLM, Snowflake auth failure, network failure, query timeout, frontend failure.

## 12. Performance Results

Status: **PASS locally, NOT TESTED deployed**

20 representative local requests against Snowflake:

```text
count 20
min 0ms
median 1154ms
p90 1672ms
p95 1813ms
max 2550ms
```

The local result is comfortably under 60 seconds. It does not prove public deployed latency.

Timeout evidence:
- Snowflake statement timeout set from settings: `app/database/query_executor.py:25-26`.
- Query timeout default is 30 seconds: `app/config.py:30`.
- Hosted LLM timeout default is 20 seconds: `app/config.py:19`, used in `app/agent/hosted_llm_client.py:20-23`.

## 13. UI Evaluation

Status: **PARTIAL / NOT TESTED deployed**

Evidence:
- Streamlit chat UI exists: `frontend/streamlit_app.py:11-78`.
- Suggested prompts use same `agent.answer` path as typed prompts: `frontend/streamlit_app.py:31-62`.
- Loading spinner exists: `frontend/streamlit_app.py:60-62`.
- Interpretation and SQL are inspectable: `frontend/streamlit_app.py:64-69`.
- Sidebar shows Snowflake/LLM config status: `frontend/streamlit_app.py:22-30`.

Limitations:
- No public URL, no clean-browser test, no screenshots.
- No explicit reset button.
- No charts.
- No table component for large results.
- Accessibility/mobile/contrast/focus states not tested.

## 14. Test Results

Command:

```text
.\.venv\Scripts\python.exe -m pytest
```

Output:

```text
collected 22 items
tests\golden\test_golden_cases.py .
tests\golden\test_requested_question_set.py ..
tests\unit\test_context_resolver.py ...
tests\unit\test_geography.py ..
tests\unit\test_guardrails.py ..
tests\unit\test_public_mode.py .
tests\unit\test_query_pipeline.py ...........
22 passed, 2 warnings in 26.67s
```

Warnings:
- `pyarrow` version warning from Snowflake connector.
- pytest cache write warning due local `.pytest_cache` access.

Test grouping:
- Unit: geography, guardrails, context resolver, public mode, query pipeline.
- Golden/planner: `tests/golden/test_golden_cases.py`, first half of `test_requested_question_set.py`.
- Live Snowflake: `tests/golden/test_requested_question_set.py:66-77`, skipped only when credentials are absent.
- Live LLM: none.
- Deployed E2E: none.

Critical grounding probe:

```text
ANSWER1: Using the available 2020 Census dataset, California's total population was 987,654,321 people.
ANSWER2: Using the available 2020 Census dataset, California's total population was 123,456,789 people.
DIFFERENT: True
```

This proves the answer generator depends on supplied rows, but it is a direct unit probe, not a Snowflake monkeypatch/integration test.

## 15. Deployment Truth

Status: **FAIL**

Evidence:
- No live URL in `README.md`.
- Deployment instructions exist: `docs/deployment.md:1-51`.
- Render blueprint exists: `render.yaml:1-16`.
- `git status --short` showed all project files untracked, indicating no committed project state ready to push.

Not verified:
- Public frontend load.
- Health endpoint from public URL.
- Diagnostics endpoint.
- Public Snowflake connectivity.
- Public LLM configuration.
- Clean incognito session.
- Fresh restart behavior.
- CORS restrictions.
- Production logs.

## 16. Documentation Evaluation

README:
- PASS: identifies Snowflake dataset: `README.md:33-37`.
- PASS: explains request lifecycle: `README.md:9-21`.
- PASS: documents env vars: `README.md:136-148`, `.env.example:1-14`.
- PARTIAL: live URL missing.
- PARTIAL: top-level LLM wording overstates implementation because default production does not use LLM: `README.md:5`.
- PASS: limitations listed: `README.md:152-156`.

Reflection:
- PASS: concrete design process/tradeoffs: `docs/reflection.md:3-17`.
- PASS: known limits and improvements: `docs/reflection.md:38-50`.
- PARTIAL: should explicitly state deployment and real-LLM gaps if those remain at submission time.

## 17. Interview Questions for the Candidate

1. Show a deployed Gemini trace proving `llm_attempted=true` and `llm_succeeded=true`.
2. What exact deployed URL should the evaluator open?
3. How do you prove deployed answers come from Snowflake, not from local tests?
4. Why does the poverty-rate answer return `72` instead of a geography name?
5. Why is SQL validation regex-based rather than AST/table-metadata based?
6. How would your system answer a metric not present in `verified_metrics.json`?
7. What protects against duplicate block-group rows and double-counting?
8. Why is median household income computed as `APPROX_PERCENTILE` of block-group medians?
9. How would context survive multiple workers or restarts?
10. What are the top three failures you would fix before a customer demo?

## 18. Final Recommendation

Do not submit as final until these are fixed:

1. Deploy a public app and add the live URL to the README.
2. Configure and verify a reachable hosted LLM if the assignment requires real LLM production behavior, or explicitly defend deterministic parsing and accept the LLM score cap.
3. Run and record public deployment smoke tests: successful question, follow-up, clarification, off-topic refusal, Snowflake failure.
4. Strengthen SQL validation with AST/table/function/LIMIT checks.
5. Expand geography labeling to include Puerto Rico or filter to US states when the question says “state.”
6. Commit and push the repository state over SSH so the deployment is reproducible.

## 19. Required Fixes Before Submission

Critical:
- Public deployment URL.
- Hosted LLM production trace or clear deterministic-only positioning.
- README live URL and deployment verification evidence.

High:
- SQL validator hardening.
- Puerto Rico/state-label handling.
- Persistent session store for production.
- Deployed latency and health checks.

Medium:
- Broader metadata-driven schema selection.
- More guardrail and failure-injection tests.
- UI reset, result tables, mobile screenshots, and accessibility checks.
