from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GoogleNewsSource:
    name: str
    query: str
    hl: str = "ja"
    gl: str = "JP"
    ceid: str = "JP:ja"
    country: str = ""


@dataclass(frozen=True)
class PageSource:
    name: str
    url: str
    allow_url_patterns: list[str]
    max_links: int | None = None
    parser: str = "links"
    country: str = ""


@dataclass(frozen=True)
class WatchConfig:
    minimum_score: int
    google_news_queries: list[str]
    google_news_sources: list[GoogleNewsSource]
    page_sources: list[PageSource]
    exclude_urls: list[str]
    exclude_title_patterns: list[str]
    generic_link_title_patterns: list[str]
    categories: dict[str, list[str]]
    keyword_weights: dict[str, int]
    sales_angles: dict[str, str]


def load_config(path: Path) -> WatchConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return WatchConfig(
        minimum_score=int(raw.get("minimum_score", 3)),
        google_news_queries=list(raw.get("google_news_queries", [])),
        google_news_sources=[
            GoogleNewsSource(
                name=str(item.get("name", item["query"])),
                query=str(item["query"]),
                hl=str(item.get("hl", "ja")),
                gl=str(item.get("gl", "JP")),
                ceid=str(item.get("ceid", "JP:ja")),
                country=str(item.get("country", "")),
            )
            for item in raw.get("google_news_sources", [])
        ],
        page_sources=[
            PageSource(
                name=item["name"],
                url=item["url"],
                allow_url_patterns=[
                    str(pattern) for pattern in item.get("allow_url_patterns", [])
                ],
                max_links=(
                    int(item["max_links"])
                    if item.get("max_links") is not None
                    else None
                ),
                parser=str(item.get("parser", "links")),
                country=str(item.get("country", "")),
            )
            for item in raw.get("page_sources", [])
        ],
        exclude_urls=[str(url) for url in raw.get("exclude_urls", [])],
        exclude_title_patterns=[
            str(pattern) for pattern in raw.get("exclude_title_patterns", [])
        ],
        generic_link_title_patterns=[
            str(pattern) for pattern in raw.get("generic_link_title_patterns", [])
        ],
        categories={
            str(name): [str(term) for term in terms]
            for name, terms in raw.get("categories", {}).items()
        },
        keyword_weights={
            str(term): int(weight)
            for term, weight in raw.get("keyword_weights", {}).items()
        },
        sales_angles={
            str(category): str(angle)
            for category, angle in raw.get("sales_angles", {}).items()
        },
    )


def config_to_jsonable(config: WatchConfig) -> dict[str, Any]:
    return {
        "minimum_score": config.minimum_score,
        "google_news_queries": config.google_news_queries,
        "google_news_sources": [source.__dict__ for source in config.google_news_sources],
        "page_sources": [source.__dict__ for source in config.page_sources],
        "exclude_urls": config.exclude_urls,
        "exclude_title_patterns": config.exclude_title_patterns,
        "generic_link_title_patterns": config.generic_link_title_patterns,
        "categories": config.categories,
        "keyword_weights": config.keyword_weights,
        "sales_angles": config.sales_angles,
    }
