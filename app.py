from __future__ import annotations

from io import BytesIO
from html import escape

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
    .stTextInput input, .stSelectbox div[data-baseweb="select"], textarea {
        background-color: #eaf8ff !important;
        color: #ffffff !important;
        border: 1px solid #c9ecff !important;
        border-radius: 10px !important;
    }
    .stTextInput input::placeholder, textarea::placeholder {
        color: rgba(255, 255, 255, 0.78) !important;
    }
    .stSelectbox div[data-baseweb="select"] span,
    .stSelectbox div[data-baseweb="select"] div {
        color: #ffffff !important;
    }
    .stSlider {
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
    div[data-testid="stDataFrame"], .result-table-wrap {
        background-color: rgba(255, 255, 255, 0.72);
        border-radius: 12px;
        padding: 8px;
    }
    .result-table {
        width: 100%;
        border-collapse: collapse;
        color: #0b3d91;
        font-size: 0.94rem;
    }
    .result-table th {
        background-color: #c7e7ff;
        color: #073b7a;
        text-align: left;
        padding: 8px;
        border: 1px solid #9fd3ff;
    }
    .result-table td {
        padding: 8px;
        border: 1px solid #b9dfff;
        background-color: rgba(234, 248, 255, 0.9);
        color: #0b3d91;
    }
    .result-table a {
        color: #2f7ed8;
        font-weight: 700;
        text-decoration: underline;
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
            worksheet.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 55)
    return buffer.getvalue()


def make_source_link(title: str, url: str) -> str:
    """HTML-ссылка для отображения источника в итоговой таблице."""
    safe_title = escape((title or url or "Источник").strip())
    safe_url = escape((url or "").strip(), quote=True)
    if not safe_url:
        return safe_title
    return f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{safe_title}</a>'


def render_html_table(df: pd.DataFrame) -> None:
    html_table = df.to_html(index=False, escape=False, classes="result-table")
    st.markdown(f'<div class="result-table-wrap">{html_table}</div>', unsafe_allow_html=True)


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
        st.write(f"1. Ищу сочетание: {field_1.strip()} + {field_2.strip()} + {code.strip()} через {search_engine_label}.")
        sources = collect_sources(code, field_1, field_2, max_sources=max_sources, search_engine=selected_search_engine)

        if not sources:
            status.update(label="Источники не найдены", state="error")
            st.warning("Не удалось найти доступные источники. Попробуйте выбрать другой поисковик, убрать лишние слова из классификации или проверить код модели.")
            st.stop()

        st.write(f"2. Открыто и отобрано источников, где найден код модели: {len(sources)}.")
        st.write(f"3. Последовательно извлекаю характеристики по каждому источнику через нейросеть: {selected_model}.")

        hf_token = st.secrets.get("HF_TOKEN", None) if hasattr(st, "secrets") else None
        rows = extract_with_hf_llm(sources, code, hf_token=hf_token, model=selected_model)

        if not rows:
            st.write("4. LLM недоступна или не вернула JSON. Использую резервное извлечение по шаблонам.")
            rows = extract_with_regex(sources, code)
        else:
            st.write("4. Характеристики получены от LLM.")

        status.update(label="Готово", state="complete")

    if not rows:
        st.warning("Характеристики не найдены. Попробуйте увеличить число источников или уточнить код модели.")
    else:
        display_rows = []
        download_rows = []
        for r in rows:
            source_title = r.get("source_title", "") or "Источник"
            source_url = r.get("source_url", "")
            source_label = source_title
            for source in sources:
                if source.get("url") == source_url:
                    source_label = source.get("site_name") or source_title
                    break

            common = {
                "Класс": field_1.strip(),
                "Подкласс": field_2.strip(),
                "Код модели": code.strip(),
                "Характеристика": r.get("characteristic", ""),
                "Значение": r.get("value", ""),
                "Ед. изм.": r.get("unit", ""),
            }
            display_rows.append({**common, "Источник": make_source_link(source_label, source_url)})
            download_rows.append({**common, "Источник": f"{source_label} - {source_url}" if source_url else source_label})

        df_display = pd.DataFrame(display_rows)
        df_download = pd.DataFrame(download_rows)
        st.subheader("Таблица характеристик")
        render_html_table(df_display)

        safe_code = code.strip().replace(" ", "_").replace("/", "_")
        csv = df_download.to_csv(index=False, sep=";").encode("utf-8-sig")
        xlsx = dataframe_to_xlsx_bytes(df_download)

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
