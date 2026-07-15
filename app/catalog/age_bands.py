from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgeBand:
    label: str
    min_age: int
    max_age: int | None
    male_column: str
    female_column: str

    @property
    def columns(self) -> list[str]:
        return [self.male_column, self.female_column]


AGE_BANDS = [
    AgeBand("under 5", 0, 4, "B01001e3", "B01001e27"),
    AgeBand("5 to 9", 5, 9, "B01001e4", "B01001e28"),
    AgeBand("10 to 14", 10, 14, "B01001e5", "B01001e29"),
    AgeBand("15 to 17", 15, 17, "B01001e6", "B01001e30"),
    AgeBand("18 and 19", 18, 19, "B01001e7", "B01001e31"),
    AgeBand("20", 20, 20, "B01001e8", "B01001e32"),
    AgeBand("21", 21, 21, "B01001e9", "B01001e33"),
    AgeBand("22 to 24", 22, 24, "B01001e10", "B01001e34"),
    AgeBand("25 to 29", 25, 29, "B01001e11", "B01001e35"),
    AgeBand("30 to 34", 30, 34, "B01001e12", "B01001e36"),
    AgeBand("35 to 39", 35, 39, "B01001e13", "B01001e37"),
    AgeBand("40 to 44", 40, 44, "B01001e14", "B01001e38"),
    AgeBand("45 to 49", 45, 49, "B01001e15", "B01001e39"),
    AgeBand("50 to 54", 50, 54, "B01001e16", "B01001e40"),
    AgeBand("55 to 59", 55, 59, "B01001e17", "B01001e41"),
    AgeBand("60 and 61", 60, 61, "B01001e18", "B01001e42"),
    AgeBand("62 to 64", 62, 64, "B01001e19", "B01001e43"),
    AgeBand("65 and 66", 65, 66, "B01001e20", "B01001e44"),
    AgeBand("67 to 69", 67, 69, "B01001e21", "B01001e45"),
    AgeBand("70 to 74", 70, 74, "B01001e22", "B01001e46"),
    AgeBand("75 to 79", 75, 79, "B01001e23", "B01001e47"),
    AgeBand("80 to 84", 80, 84, "B01001e24", "B01001e48"),
    AgeBand("85 and older", 85, None, "B01001e25", "B01001e49"),
]


def age_range_label(age_min: int | None, age_max: int | None) -> str:
    if age_min is not None and age_max is not None:
        return f"age {age_min} to {age_max}"
    if age_min is not None:
        return f"age {age_min} and older"
    if age_max is not None:
        return f"under age {age_max + 1}"
    return "all ages"


def columns_for_age_range(age_min: int | None, age_max: int | None) -> list[str]:
    columns: list[str] = []
    for band in AGE_BANDS:
        band_max = band.max_age if band.max_age is not None else 200
        requested_min = age_min if age_min is not None else 0
        requested_max = age_max if age_max is not None else 200
        if band.min_age <= requested_max and band_max >= requested_min:
            columns.extend(band.columns)
    return columns
