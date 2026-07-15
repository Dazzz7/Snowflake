from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database.snowflake_client import snowflake_connection


TABLES = [
    "2020_CBG_B01",
    "2020_CBG_B02",
    "2020_CBG_B15",
    "2020_CBG_B17",
    "2020_CBG_B19",
    "2020_CBG_B22",
    "2020_CBG_B27",
    "2020_CBG_B28",
]


def main() -> None:
    with snowflake_connection() as conn:
        cursor = conn.cursor()
        try:
            placeholders = ", ".join(["%s"] * len(TABLES))
            cursor.execute(
                f"""
SELECT table_name, column_name
FROM {settings.snowflake_database}.information_schema.columns
WHERE table_schema = %s
  AND table_name IN ({placeholders})
ORDER BY table_name, ordinal_position
""".strip(),
                [settings.snowflake_schema, *TABLES],
            )
            current_table = None
            for table_name, column_name in cursor.fetchall():
                if table_name != current_table:
                    current_table = table_name
                    print(f"\n{table_name}")
                print(column_name)
        finally:
            cursor.close()


if __name__ == "__main__":
    main()
