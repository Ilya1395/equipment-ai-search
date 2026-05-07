from __future__ import annotations

import re

UNIT_MAP = {
    "киловатт": "кВт",
    "квт": "кВт",
    "kw": "кВт",
    "w": "Вт",
    "вт": "Вт",
    "килограмм": "кг",
    "кг": "кг",
    "тонна": "т",
    "т": "т",
    "метр": "м",
    "м": "м",
    "миллиметр": "мм",
    "мм": "мм",
    "куб.м/ч": "м3/ч",
    "м³/ч": "м3/ч",
    "м3/ч": "м3/ч",
    "куб. м/ч": "м3/ч",
    "м³/мин": "м3/мин",
    "м3/мин": "м3/мин",
    "литр/с": "л/с",
    "л/с": "л/с",
    "об/мин": "об/мин",
    "rpm": "об/мин",
    "вольт": "В",
    "в": "В",
    "ампер": "А",
    "а": "А",
    "гц": "Гц",
    "hz": "Гц",
    "бар": "бар",
    "мпа": "МПа",
    "°c": "°C",
    "c": "°C",
    "с": "°C",
}


def normalize_unit(unit: str) -> str:
    unit = (unit or "").strip().replace("м³", "м3")
    key = unit.lower().strip(" .,")
    return UNIT_MAP.get(key, unit)


def clean_value(value: str) -> str:
    value = str(value or "").strip()
    value = value.replace("—", "-").replace("–", "-")
    value = re.sub(r"\s+", " ", value)
    return value


def deduplicate(rows: list[dict]) -> list[dict]:
    """Удаляет дубли, сохраняя источник, если он был найден."""
    seen = set()
    out = []
    for row in rows:
        char = str(row.get("characteristic", "")).strip()
        val = clean_value(row.get("value", ""))
        unit = normalize_unit(str(row.get("unit", "")))
        source_title = str(row.get("source_title", "")).strip()
        source_url = str(row.get("source_url", "")).strip()
        if not char or not val:
            continue
        key = (char.lower(), val.lower(), unit.lower(), source_url.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "characteristic": char,
                "value": val,
                "unit": unit,
                "source_title": source_title,
                "source_url": source_url,
            }
        )
    return out
