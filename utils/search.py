from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Iterable, Literal
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


REQUEST_DELAY_SECONDS = 2
SEARCH_TIMEOUT_SECONDS = 25
PAGE_TIMEOUT_SECONDS = 20

SearchEngine = Literal["google", "yandex", "yahoo"]

SEARCH_ENGINE_LABELS = {
    "google": "Google.com",
    "yandex": "Ya.ru",
    "yahoo": "Yahoo.com",
}

SEARCH_ENDPOINTS: dict[str, list[str]] = {
    "google": [
        "https://www.google.com/search",
    ],
    "yandex": [
        "https://ya.ru/search/",
        "https://yandex.ru/search/",
        "https://ya.ru/search/touch/",
        "https://yandex.ru/search/touch/",
    ],
    "yahoo": [
        "https://search.yahoo.com/search",
    ],
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.7,en;q=0.6",
    "Connection": "keep-alive",
}

INTERNAL_HOST_PARTS = (
    "ya.ru",
    "yandex.ru",
    "yandex.com",
    "yastatic.net",
    "yabs.yandex",
    "mc.yandex",
    "metrika.yandex",
    "google.com",
    "google.ru",
    "gstatic.com",
    "googleusercontent.com",
    "search.yahoo.com",
    "yahoo.com",
    "yimg.com",
    "bing.com",
)

BAD_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".css",
    ".js",
    ".ico",
)


@dataclass
class SearchResult:
    title: str
    href: str
    body: str = ""


def build_queries(code: str, class_name: str, subclass_name: str) -> list[str]:
    clean_code = code.strip()
    cls = class_name.strip()
    subcls = subclass_name.strip()
    return [
        f'"{clean_code}" характеристики {cls} {subcls}',
        f'"{clean_code}" технические характеристики',
        f'"{clean_code}" паспорт инструкция pdf',
        f'"{clean_code}" каталог {cls}',
        f'{clean_code} {cls} {subcls} производительность мощность масса',
    ]


def _clean_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _is_internal_host(host: str) -> bool:
    host = (host or "").lower()
    return any(part in host for part in INTERNAL_HOST_PARTS)


def _looks_like_bad_resource(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(BAD_EXTENSIONS)


def _extract_target_from_query(parsed) -> str:
    params = parse_qs(parsed.query)
    for key in ("url", "u", "target", "to", "href", "source", "uddg"):
        values = params.get(key)
        if not values:
            continue
        candidate = unquote(values[0])
        if candidate.startswith(("http://", "https://")):
            return candidate
    return ""


def _extract_google_url(href: str) -> str:
    parsed = urlparse(href)
    if parsed.path == "/url":
        params = parse_qs(parsed.query)
        values = params.get("q") or params.get("url")
        if values and values[0].startswith(("http://", "https://")):
            return values[0]
    return ""


def _normalize_search_url(href: str, base_url: str) -> str:
    href = (href or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return ""

    href = urljoin(base_url, href)
    parsed = urlparse(href)

    google_target = _extract_google_url(href)
    if google_target:
        href = google_target
        parsed = urlparse(href)

    if _is_internal_host(parsed.netloc):
        extracted = _extract_target_from_query(parsed)
        if extracted:
            href = extracted
            parsed = urlparse(href)
        else:
            return ""

    if not href.startswith(("http://", "https://")):
        return ""
    if _is_internal_host(parsed.netloc):
        return ""
    if _looks_like_bad_resource(href):
        return ""

    return href


def _container_text_for_link(link) -> str:
    parent = link
    for _ in range(5):
        parent = parent.parent if parent else None
        if not parent:
            break
        text = _clean_text(parent.get_text(" ", strip=True))
        if len(text) >= 25:
            return text
    return _clean_text(link.get_text(" ", strip=True))


def _title_for_link(link, container_text: str) -> str:
    title = _clean_text(link.get_text(" ", strip=True))
    if title and len(title) >= 3:
        return title[:180]
    return container_text[:120] if container_text else "Найденный источник"


def _parse_results(html: str, base_url: str) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []
    seen: set[str] = set()

    for link in soup.select("a[href]"):
        href = _normalize_search_url(link.get("href", ""), base_url=base_url)
        if not href or href in seen:
            continue

        container_text = _container_text_for_link(link)
        lower_text = container_text.lower()
        if any(marker in lower_text for marker in ("captcha", "подтвердите", "unusual traffic", "robot")):
            continue

        title = _title_for_link(link, container_text)
        if not title:
            continue

        snippet = container_text
        if snippet.startswith(title):
            snippet = snippet[len(title):].strip(" -–—|·")
        snippet = snippet[:900]

        seen.add(href)
        results.append(SearchResult(title=title, href=href, body=snippet))

    return results


def _request_search(endpoint: str, query: str, search_engine: SearchEngine) -> tuple[str, str]:
    if search_engine == "google":
        params = {"q": query, "num": "10", "hl": "ru"}
    elif search_engine == "yahoo":
        params = {"p": query, "n": "10"}
    else:
        params = {"text": query, "lr": "213"}

    response = requests.get(
        endpoint,
        params=params,
        headers=HEADERS,
        timeout=SEARCH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.text, response.url


def web_search(queries: Iterable[str], max_results: int = 8, search_engine: SearchEngine = "yandex") -> list[SearchResult]:
    search_engine = search_engine if search_engine in SEARCH_ENDPOINTS else "yandex"
    endpoints = SEARCH_ENDPOINTS[search_engine]
    seen: set[str] = set()
    results: list[SearchResult] = []

    for query_index, query in enumerate(queries):
        if query_index > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        for endpoint_index, endpoint in enumerate(endpoints):
            if endpoint_index > 0:
                time.sleep(REQUEST_DELAY_SECONDS)

            try:
                html, final_url = _request_search(endpoint, query, search_engine)
            except Exception:
                continue

            for item in _parse_results(html, base_url=final_url):
                if item.href in seen:
                    continue
                seen.add(item.href)
                results.append(item)
                if len(results) >= max_results:
                    return results

    return results[:max_results]


def fetch_page_text(url: str, timeout: int = PAGE_TIMEOUT_SECONDS, max_chars: int = 14000) -> str:
    time.sleep(REQUEST_DELAY_SECONDS)

    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
    except Exception:
        return ""

    content_type = response.headers.get("content-type", "").lower()
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        return "PDF-документ найден. В этой версии PDF напрямую не читается, но его название и сниппет поисковой выдачи используются для анализа."

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "form"]):
        tag.decompose()

    parts: list[str] = []
    for element in soup.find_all(["h1", "h2", "h3", "p", "li", "td", "th", "span"]):
        text = _clean_text(element.get_text(" ", strip=True))
        if len(text) >= 3:
            parts.append(text)

    text = "\n".join(parts)
    return text[:max_chars]


def collect_sources(
    code: str,
    class_name: str,
    subclass_name: str,
    max_sources: int = 6,
    search_engine: SearchEngine = "yandex",
) -> list[dict]:
    results = web_search(
        build_queries(code, class_name, subclass_name),
        max_results=max_sources,
        search_engine=search_engine,
    )
    sources: list[dict] = []

    for result in results:
        page_text = fetch_page_text(result.href)
        combined = "\n".join([result.title, result.body, page_text]).strip()
        if combined:
            sources.append({"title": result.title, "url": result.href, "text": combined})

    return sources
