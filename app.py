from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st

from utils.llm import MODEL_OPTIONS, extract_with_hf_llm, extract_with_regex
from utils.search import SEARCH_ENGINE_LABELS, collect_sources

st.set_page_config(page_title="Поиск характеристик оборудования", layout="wide")

st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #dff6ff 0%, #c7e7ff 45%, #b6ccff 100%);
        color: #0b3d91;
    }
    h1, h2, h3, h4, h5, h6, p, label, span, div {
        color: #0b3d91;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #c2e9fb 0%, #a1c4fd 100%);
    }
    [data-testid="stHeader"] {
        background: rgba(223, 246, 255, 0.75);
    }
    .stTextInput input, .stSelectbox div[data-baseweb="select"], .stSlider, textarea {
        color: #0b3d91;
    }
    .stButton > button, .stDownloadButton > button {
        background-color: #ffb3b3;
        color: #073b7a;
        border: 1px solid #ff8f8f;
        border-radius: 10px;
        font-weight: 700;
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
        background-color: #ff9f9f;
        color: #002f6c;
        border-color: #ff7f7f;
    }
    div[data-testid="stDataFrame"] {
        background-color: rgba(255, 255, 255, 0.7);
        border-radius: 12px;
        padding: 6px;
    }
    .main-title-small {
        font-size: 1.55rem;
        font-weight: 700;
        color: #084c9e;
        margin-bottom: 0.25rem;
    }
    .subtitle-blue {
        font-size: 1rem;
        color: #2f7ed8;
        margin-bottom: 1.2rem;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title-small">Поиск характеристик моделей оборудования</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle-blue">Поиск по открытым источникам характеристик</div>', unsafe_allow_html=True)


def dataframe_to_xlsx_bytes(df: pd.DataFrame) -> bytes:
    """Возвращает XLSX-файл в байтах для st.download_button."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Характеристики")
        worksheet = writer.sheets["Характеристики"]
        for column_cells in worksheet.columns:
            max_length = max(len(str(cell.value or "")) for cell in column_cells)
            column_letter = column_cells[0].column_letter
            worksheet.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 45)
    return buffer.getvalue()


with st.sidebar:
    st.header("Настройки")
    search_engine_label = st.selectbox(
        "Поисковик",
        list(SEARCH_ENGINE_LABELS.values()),
        index=1,
        help="Выберите поисковую систему для поиска открытых источников.",
    )
    selected_search_engine = next(
        key for key, value in SEARCH_ENGINE_LABELS.items() if value == search_engine_label
    )

    max_sources = st.slider("Количество источников для анализа", 3, 50, 10)

    model_labels = list(MODEL_OPTIONS.keys())
    selected_model_label = st.selectbox(
        "Нейросеть для извлечения характеристик",
        model_labels,
        index=0,
        help="Все варианты являются open-source моделями, доступными через Hugging Face. Фактическая доступность зависит от бесплатных лимитов и прав доступа Hugging Face.",
    )
    selected_model = MODEL_OPTIONS[selected_model_label]

    custom_model = st.text_input(
        "Своя модель Hugging Face, необязательно",
        placeholder="Например: Qwen/Qwen2.5-7B-Instruct",
        help="Если заполнить это поле, приложение использует его вместо выбранного значения из списка.",
    ).strip()
    if custom_model:
        selected_model = custom_model

    show_sources = st.checkbox("Показывать найденные источники", value=True)
    st.info(
        "Для работы нейросети добавьте HF_TOKEN в secrets Streamlit. "
        "Без токена сработает только резервное извлечение по шаблонам."
    )

col1, col2, col3 = st.columns(3)
with col1:
    field_1 = st.text_input("Класс", placeholder="Например: Насосы")
with col2:
    field_2 = st.text_input("Подкласс", placeholder="Например: Погружные")
with col3:
    code = st.text_input("Код модели", placeholder="Например: ГНОМ 40-25")

run = st.button("Найти характеристики", type="primary", use_container_width=True)

if run:
    if not code.strip() or not field_1.strip() or not field_2.strip():
        st.error("Заполните поля: Класс, Подкласс и Код модели.")
        st.stop()

    with st.status("Ищу открытые источники и извлекаю характеристики...", expanded=True) as status:
        st.write(f"1. Выполняю поиск через {search_engine_label} с задержкой 2 секунды между запросами.")
        sources = collect_sources(code, field_1, field_2, max_sources=max_sources, search_engine=selected_search_engine)

        if not sources:
            status.update(label="Источники не найдены", state="error")
            st.warning("Не удалось найти доступные источники. Попробуйте выбрать другой поисковик, убрать лишние слова из классификации или проверить код модели.")
            st.stop()

        st.write(f"2. Найдено источников: {len(sources)}.")
        st.write(f"3. Передаю найденный текст в нейросеть: {selected_model}.")

        hf_token = st.secrets.get("HF_TOKEN", None) if hasattr(st, "secrets") else None
        rows = extract_with_hf_llm(sources, code, hf_token=hf_token, model=selected_model)

        if not rows:
            st.write("4. LLM недоступна или не вернула JSON. Использую резервное извлечение по шаблонам.")
            rows = extract_with_regex(sources)
        else:
            st.write("4. Характеристики получены от LLM.")

        status.update(label="Готово", state="complete")

    if not rows:
        st.warning("Характеристики не найдены. Попробуйте увеличить число источников или уточнить код модели.")
    else:
        table_rows = [
            {
                "Класс": field_1.strip(),
                "Подкласс": field_2.strip(),
                "Код модели": code.strip(),
                "Характеристика": r.get("characteristic", ""),
                "Значение": r.get("value", ""),
                "Ед. изм.": r.get("unit", ""),
            }
            for r in rows
        ]
        df = pd.DataFrame(table_rows)
        st.subheader("Таблица характеристик")
        st.dataframe(df, use_container_width=True, hide_index=True)

        safe_code = code.strip().replace(" ", "_").replace("/", "_")
        csv = df.to_csv(index=False, sep=";").encode("utf-8-sig")
        xlsx = dataframe_to_xlsx_bytes(df)

        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                "Скачать CSV",
                data=csv,
                file_name=f"{safe_code}_characteristics.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with dl_col2:
            st.download_button(
                "Скачать XLSX",
                data=xlsx,
                file_name=f"{safe_code}_characteristics.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    if show_sources:
        st.subheader("Использованные источники")
        for i, source in enumerate(sources, 1):
            title = source.get("title") or source.get("url")
            st.markdown(f"{i}. [{title}]({source.get('url')})")
