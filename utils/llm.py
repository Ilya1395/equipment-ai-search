from __future__ import annotations

import json
import os
import re
from typing import Any

from huggingface_hub import InferenceClient

from .normalize import deduplicate

MODEL_OPTIONS = {
    "Qwen 2.5 7B Instruct": "Qwen/Qwen2.5-7B-Instruct",
    "Mistral 7B Instruct v0.3": "mistralai/Mistral-7B-Instruct-v0.3",
    "Zephyr 7B Beta": "HuggingFaceH4/zephyr-7b-beta",
    "Falcon 7B Instruct": "tiiuae/falcon-7b-instruct",
    "Phi-3 Mini 4K Instruct": "microsoft/Phi-3-mini-4k-instruct",
    "Gemma 2 2B IT": "google/gemma-2-2b-it",
}

DEFAULT_MODEL = MODEL_OPTIONS["Qwen 2.5 7B Instruct"]

SYSTEM_INSTRUCTION = """
Ты извлекаешь технические характеристики оборудования из текста одного открытого источника.
Верни только JSON-массив объектов без пояснений.
Каждый объект: {"characteristic":"название характеристики", "value":"значение", "unit":"единица измерения"}.
Не выдумывай. Извлекай только то, что прямо указано в тексте источника рядом с указанным кодом модели.
Если значение или единица не указаны, оставь пустую строку.
Единицы измерения сокращай: кг, т, кВт, Вт, В, А, Гц, м, мм, м3/ч, м3/мин, л/с, об/мин, МПа, бар, °C.
Если в источнике указана единица м³/ч, верни м3/ч.
""".strip()


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def _source_contains_code(source_text: str, code: str) -> bool:
    normalized_text = re.sub(r"\s+", "", (source_text or "").lower())
    normalized_code = re.sub(r"\s+", "", (code or "").lower())
    return bool(normalized_code and normalized_code in normalized_text)


def _extract_one_source_with_hf(client: InferenceClient, source: dict, code: str) -> list[dict]:
    source_text = source.get("text", "")[:12000]
    prompt = f"""
{SYSTEM_INSTRUCTION}

Код модели: {code}
Название источника: {source.get('title', '')}
URL источника: {source.get('url', '')}

Текст источника:
{source_text}

JSON:
""".strip()

    try:
        response = client.chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
            max_tokens=900,
            temperature=0.0,
        )
        content = response.choices[0].message.content or ""
    except Exception:
        content = client.text_generation(prompt, max_new_tokens=900, temperature=0.01)

    rows = _extract_json_array(content)
    for row in rows:
        row["source_title"] = source.get("title", "")
        row["source_url"] = source.get("url", "")
    return rows


def extract_with_hf_llm(
    sources: list[dict],
    code: str,
    hf_token: str | None = None,
    model: str | None = None,
) -> list[dict]:
    """Извлекает характеристики отдельно по каждому найденному сайту, чтобы сохранить источник."""
    token = hf_token or os.getenv("HF_TOKEN")
    model_id = model or os.getenv("HF_MODEL") or DEFAULT_MODEL
    if not token:
        return []

    try:
        client = InferenceClient(model=model_id, token=token)
    except Exception:
        return []

    all_rows: list[dict] = []
    for source in sources:
        # Источник уже найден поисковиком по сочетанию Класс + Подкласс + Код модели.
        # Код может отсутствовать в доступном HTML из-за защиты сайта, карточек товара, PDF или динамической загрузки.
        # Поэтому не отбрасываем источник на этом этапе, а просим LLM извлечь только явно указанные характеристики.
        try:
            all_rows.extend(_extract_one_source_with_hf(client, source, code))
        except Exception:
            continue

    return deduplicate(all_rows)


COMMON_PATTERNS = [
    r"(?P<name>производительность|подача)\s*[:\-–]?\s*(?P<value>\d+[\d,.\- ]*)\s*(?P<unit>м3/ч|м³/ч|м3/мин|м³/мин|л/с)",
    r"(?P<name>мощность(?: двигателя)?)\s*[:\-–]?\s*(?P<value>\d+[\d,.\- ]*)\s*(?P<unit>кВт|kw|вт)",
    r"(?P<name>масса|вес)\s*[:\-–]?\s*(?P<value>\d+[\d,.\- ]*)\s*(?P<unit>кг|т)",
    r"(?P<name>напор)\s*[:\-–]?\s*(?P<value>\d+[\d,.\- ]*)\s*(?P<unit>м)",
    r"(?P<name>напряжение)\s*[:\-–]?\s*(?P<value>\d+[\d,.\- ]*)\s*(?P<unit>В|V)",
    r"(?P<name>частота)\s*[:\-–]?\s*(?P<value>\d+[\d,.\- ]*)\s*(?P<unit>Гц|Hz)",
    r"(?P<name>частота вращения|обороты)\s*[:\-–]?\s*(?P<value>\d+[\d,.\- ]*)\s*(?P<unit>об/мин|rpm)",
    r"(?P<name>диаметр(?: патрубка| прохода)?)\s*[:\-–]?\s*(?P<value>\d+[\d,.\- ]*)\s*(?P<unit>мм|м)",
    r"(?P<name>температура(?: жидкости| среды)?)\s*[:\-–]?\s*(?P<value>\d+[\d,.\- ]*)\s*(?P<unit>°C|С|C)",
]


def extract_with_regex(sources: list[dict], code: str | None = None) -> list[dict]:
    rows = []
    for source in sources:
        text = source.get("text", "")
        lower_text = text.lower()
        for pattern in COMMON_PATTERNS:
            for match in re.finditer(pattern, lower_text, flags=re.IGNORECASE):
                rows.append(
                    {
                        "characteristic": match.group("name").strip().capitalize(),
                        "value": match.group("value").strip(),
                        "unit": match.group("unit").strip(),
                        "source_title": source.get("title", ""),
                        "source_url": source.get("url", ""),
                    }
                )
    return deduplicate(rows)
