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
Ты извлекаешь технические характеристики оборудования из текста открытых источников.
Верни только JSON-массив объектов без пояснений.
Каждый объект: {"characteristic":"название характеристики", "value":"значение", "unit":"единица измерения"}.
Не выдумывай. Извлекай только то, что прямо указано в источниках.
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


def extract_with_hf_llm(
    sources: list[dict],
    code: str,
    hf_token: str | None = None,
    model: str | None = None,
) -> list[dict]:
    token = hf_token or os.getenv("HF_TOKEN")
    model_id = model or os.getenv("HF_MODEL") or DEFAULT_MODEL
    if not token:
        return []

    source_text = "\n\n".join(
        f"Источник: {s.get('title', '')}\nURL: {s.get('url', '')}\nТекст:\n{s.get('text', '')[:7000]}"
        for s in sources[:5]
    )[:26000]

    prompt = f"""
{SYSTEM_INSTRUCTION}

Модель оборудования: {code}

Текст источников:
{source_text}

JSON:
""".strip()

    try:
        client = InferenceClient(model=model_id, token=token)
        response = client.chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1000,
            temperature=0.0,
        )
        content = response.choices[0].message.content or ""
    except Exception:
        try:
            client = InferenceClient(model=model_id, token=token)
            content = client.text_generation(prompt, max_new_tokens=1000, temperature=0.01)
        except Exception:
            return []

    return deduplicate(_extract_json_array(content))


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


def extract_with_regex(sources: list[dict]) -> list[dict]:
    text = "\n".join(s.get("text", "") for s in sources).lower()
    rows = []
    for pattern in COMMON_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            rows.append(
                {
                    "characteristic": match.group("name").strip().capitalize(),
                    "value": match.group("value").strip(),
                    "unit": match.group("unit").strip(),
                }
            )
    return deduplicate(rows)
