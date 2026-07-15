from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.intent_parser import IntentParser
from app.agent.query_planner import QueryPlanner


GOLDEN_CASES = [
    {
        "question": "What is the total population of California?",
        "metric": "total_population",
        "fips": "06",
        "query_type": "aggregate_metric",
        "column": "B01003e1",
    },
    {
        "question": "Compare the populations of Texas and Florida",
        "metric": "total_population",
        "fips": "48",
        "query_type": "comparison",
        "column": "B01003e1",
    },
    {
        "question": "Top 10 states by population",
        "metric": "total_population",
        "query_type": "ranking",
        "column": "B01003e1",
    },
    {
        "question": "Which state has higher population in USA?",
        "metric": "total_population",
        "query_type": "ranking",
        "column": "B01003e1",
    },
    {
        "question": "Which states have more than 10 million people?",
        "metric": "total_population",
        "query_type": "filter",
        "column": "B01003e1",
    },
    {
        "question": "which state has more no. of people greater than 65 age",
        "metric": "population_by_age",
        "query_type": "ranking",
        "column": "B01001e20",
    },
    {
        "question": "Which state has the most people age 55 and older?",
        "metric": "population_by_age",
        "query_type": "ranking",
        "column": "B01001e17",
    },
]


def main() -> None:
    parser = IntentParser()
    planner = QueryPlanner()
    failures: list[str] = []
    for case in GOLDEN_CASES:
        intent = parser.parse(case["question"])
        plan, validation = planner.create_plan(intent)
        if not validation.is_valid or not plan:
            failures.append(f"{case['question']}: {validation.reason}")
            continue
        if intent.metric != case["metric"]:
            failures.append(f"{case['question']}: metric {intent.metric}")
        if plan.query_type != case["query_type"]:
            failures.append(f"{case['question']}: query type {plan.query_type}")
        source_columns = plan.metric.source_columns or plan.metric.estimate_columns or [plan.metric.estimate_column]
        if case["column"] not in source_columns:
            failures.append(f"{case['question']}: column {source_columns}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"{len(GOLDEN_CASES)} golden tests passed")


if __name__ == "__main__":
    main()
