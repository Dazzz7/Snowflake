from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.catalog.catalog_builder import write_columns_catalog
from app.database.schema_loader import load_columns_metadata


def main() -> None:
    result = load_columns_metadata()
    if result.error:
        raise SystemExit(result.error)
    write_columns_catalog(result.rows, "metadata/columns.json")
    print(f"Wrote {len(result.rows)} column records to metadata/columns.json")


if __name__ == "__main__":
    main()
