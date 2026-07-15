from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.catalog.metric_registry import load_metrics
from app.database.query_executor import SnowflakeQueryExecutor


def main() -> None:
    executor = SnowflakeQueryExecutor()
    for metric in load_metrics().values():
        sql = f"""
SELECT COUNT(*) AS rows_with_metric
FROM "US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET"."PUBLIC"."{metric.table}"
WHERE "{metric.estimate_column}" IS NOT NULL
LIMIT 1
""".strip()
        result = executor.execute(sql, {})
        status = "ok" if result.ok else result.error
        print(f"{metric.metric_id}: {status}")


if __name__ == "__main__":
    main()
