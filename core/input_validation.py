from __future__ import annotations

from pathlib import Path

import pandas as pd


class InputValidationError(ValueError):
    pass


def load_tasks_from_excel(path: str | Path) -> tuple[list[tuple[str, str]], int]:
    file_path = Path(path)
    if not file_path.exists():
        raise InputValidationError("Input file not found.")

    df = pd.read_excel(file_path)
    if df.empty:
        raise InputValidationError("Input file is empty.")

    normalized = {str(col).strip().lower(): col for col in df.columns}
    if "name" not in normalized or "url" not in normalized:
        raise InputValidationError("input.xlsx must contain 'name' and 'url' columns.")

    name_col = normalized["name"]
    url_col = normalized["url"]

    tasks: list[tuple[str, str]] = []
    invalid_rows = 0

    for _, row in df.iterrows():
        name = str(row.get(name_col, "")).strip()
        url = str(row.get(url_col, "")).strip()

        if not name or not url or url.lower() == "nan":
            invalid_rows += 1
            continue

        if not (url.startswith("http://") or url.startswith("https://")):
            invalid_rows += 1
            continue

        tasks.append((name, url))

    if not tasks:
        raise InputValidationError("No valid rows found. Check name/url values.")

    return tasks, invalid_rows
