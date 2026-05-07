from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote_plus, parse_qs, urlparse

import requests
from bs4 import BeautifulSoup


YANDEX_SEARCH_URL = "https://ya.ru/search/"
REQUEST_DELAY_SECONDS = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
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


def _clean_text(text: str) -> str:
    return " ".join((text or "").split())


def _normalize_yandex_url(href: str) -> str:
    """Extract a real target URL from Yandex redirect links when possible."""
    href = (href or "").strip()
    if not href:
        return ""

    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = "https://ya.ru" + href

    parsed = urlparse(href)
    if "yandex" in parsed.netloc or parsed.netloc.endswith("ya.ru"):
        params = parse_qs(parsed.query)
        for key in ("url", "u", "target"):
            if params.get(key):
                candidate = params[key][0]
                if candidate.startswith(("http://", "https://")):
                    return candidate

    return href if href.startswith(("http://", "https://")) else ""


def _parse_yandex_results(html: str) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    parsed_results: list[SearchResult] = []

    # Yandex changes markup from time to time, so several selectors are used.
    containers = soup.select("li.serp-item, div.serp-item, div[data-cid]")
    if not containers:
        containers = soup.select("a[href]")

    seen: set[str] = set()
    for container in containers:
        link = container.select_one("a.Link, a.OrganicTitle-Link, a[href]")
        if not link:
            continue

        href = _normalize_yandex_url(link.get("href", ""))
        if not href or "ya.ru" in urlparse(href).netloc or "yandex" in urlparse(href).netloc:
            continue
        if href in seen:
            continue

        title = _clean_text(link.get_text(" ", strip=True))
        snippet_el = container.select_one(".OrganicTextContentSpan, .TextContainer, .serp-item__text, .organic__text")
        body = _clean_text(snippet_el.get_text(" ", strip=True)) if snippet_el else ""

        if title:
            seen.add(href)
            parsed_results.append(SearchResult(title=title, href=href, body=body))

    return parsed_results


def web_search(queries: Iterable[str], max_results: int = 8) -> list[SearchResult]:
    seen: set[str] = set()
    results: list[SearchResult] = []

    for query in queries:
        if results:
            time.sleep(REQUEST_DELAY_SECONDS)

        try:
            response = requests.get(
                YANDEX_SEARCH_URL,
                params={"text": query},
                headers=HEADERS,
                timeout=20,
            )
            response.raise_for_status()
        except Exception:
            continue

        for item in _parse_yandex_results(response.text):
            if item.href in seen:
                continue
            seen.add(item.href)
            results.append(item)
            if len(results) >= max_results:
                return results

    return results[:max_results]


def fetch_page_text(url: str, timeout: int = 15, max_chars: int = 14000) -> str:
    time.sleep(REQUEST_DELAY_SECONDS)

    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
    except Exception:
        return ""

    content_type = response.headers.get("content-type", "").lower()
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        return "PDF-документ найден, но в этой бесплатной версии текст PDF напрямую не читается. Используйте сниппет поисковой выдачи или HTML-страницы."

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()

    parts: list[str] = []
    for element in soup.find_all(["h1", "h2", "h3", "p", "li", "td", "th"]):
        text = _clean_text(element.get_text(" ", strip=True))
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
