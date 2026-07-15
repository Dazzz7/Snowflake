from __future__ import annotations

import json
from pathlib import Path


def write_columns_catalog(rows: list[dict], output_path: str | Path) -> None:
    Path(output_path).write_text(json.dumps(rows, indent=2), encoding="utf-8")

