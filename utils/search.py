from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


@dataclass
class SearchResult:
    title: str
    href: str
    body: str = ""


def build_queries(code: str, field_1: str, field_2: str) -> list[str]:
    clean_code = code.strip()
    f1 = field_1.strip()
    f2 = field_2.strip()
    return [
        f'"{clean_code}" характеристики {f1} {f2}',
        f'"{clean_code}" технические характеристики',
        f'"{clean_code}" паспорт инструкция pdf',
        f'"{clean_code}" каталог {f1}',
    ]


def web_search(queries: Iterable[str], max_results: int = 8) -> list[SearchResult]:
    seen: set[str] = set()
    results: list[SearchResult] = []
    with DDGS(timeout=12) as ddgs:
        for query in queries:
            try:
                for item in ddgs.text(query, max_results=max_results):
                    href = item.get("href") or item.get("url") or ""
                    if not href.startswith(("http://", "https://")) or href in seen:
                        continue
                    seen.add(href)
                    results.append(
                        SearchResult(
                            title=item.get("title", ""),
                            href=href,
                            body=item.get("body", ""),
                        )
                    )
            except Exception:
                continue
    return results[:max_results]


def fetch_page_text(url: str, timeout: int = 15, max_chars: int = 14000) -> str:
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
    except Exception:
        return ""

    content_type = response.headers.get("content-type", "").lower()
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        return "PDF-документ найден, но в этой бесплатной версии текст PDF напрямую не читается. Используйте сниппет поисковой выдачи или HTML-страницы."

    soup = BeautifulSoup(response.text, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()

    parts: list[str] = []
    for element in soup.find_all(["h1", "h2", "h3", "p", "li", "td", "th"]):
        text = " ".join(element.get_text(" ", strip=True).split())
        if len(text) >= 3:
            parts.append(text)

    text = "\n".join(parts)
    return text[:max_chars]


def collect_sources(code: str, field_1: str, field_2: str, max_sources: int = 6) -> list[dict]:
    results = web_search(build_queries(code, field_1, field_2), max_results=max_sources)
    sources: list[dict] = []
    for result in results:
        page_text = fetch_page_text(result.href)
        combined = "\n".join([result.title, result.body, page_text]).strip()
        if combined:
            sources.append({"title": result.title, "url": result.href, "text": combined})
    return sources
