from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.query_executor import SnowflakeQueryExecutor


DATABASE = "US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET"


def main() -> None:
    executor = SnowflakeQueryExecutor()
    statements = [
        f"SHOW SCHEMAS IN DATABASE {DATABASE}",
        f"SHOW TABLES IN DATABASE {DATABASE}",
        f"SHOW VIEWS IN DATABASE {DATABASE}",
    ]
    for statement in statements:
        print(f"\n-- {statement}")
        result = executor.execute(statement, {})
        if result.error:
            print(result.error)
            continue
        for row in result.rows[:50]:
            print(row)


if __name__ == "__main__":
    main()
