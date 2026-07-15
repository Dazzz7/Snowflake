from __future__ import annotations

import re


def answer_uses_known_numbers(answer: str, allowed_values: list[str]) -> bool:
    numbers = re.findall(r"\b\d[\d,]*(?:\.\d+)?\b", answer)
    normalized_allowed = {value.replace(",", "") for value in allowed_values}
    for number in numbers:
        if number.replace(",", "") not in normalized_allowed and len(number) > 2:
            return False
    return True

