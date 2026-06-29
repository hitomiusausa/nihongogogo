from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import re

from .config import WatchConfig
from .deadlines import extract_deadline
from .fetchers import (
    FetchedItem,
    fetch_google_news,
    fetch_google_news_source,
    fetch_page_links,
    fetch_page_text,
    title_fingerprint,
)
from .scoring import ScoredItem, has_strong_public_signal, score_item
from .storage import WatchStore
from .summarize import summarize_detail

DOMAIN_RELEVANCE_TERMS = (
    "日本語教育",
    "日本語教室",
    "日本語学校",
    "認定日本語教育機関",
    "登録日本語教員",
    "日本語能力",
    "入学前教育",
    "予備教育",
    "留学生",
    "派遣留学生",
    "外国人材",
    "外国人介護人材",
    "介護人材",
    "在留資格",
    "出入国在留管理",
    "特定技能",
    "育成就労",
    "技能実習",
    "多文化共生",
    "異文化理解",
    "グローバル人材",
    "国際交流協会",
    "受入機関",
    "japanese",
    "japanese language",
    "specified skilled worker",
    "tokutei ginou",
    "technical intern",
    "caregiver",
    "nursing care",
    "ofw",
    "migrant worker",
    "jepang",
    "bahasa jepang",
    "pekerja migran",
    "pemagangan",
    "keterampilan khusus",
    "nhật bản",
    "tiếng nhật",
    "lao động",
    "thực tập sinh",
    "kỹ năng đặc định",
)
OFFICIAL_PUBLIC_SOURCES = {
    "文化庁 公募情報",
    "文部科学省 公募情報",
}


@dataclass(frozen=True)
class CollectionResult:
    fetched: int
    matched: int
    stored_new: int
    errors: list[str]


def run_collection(
    config: WatchConfig,
    store: WatchStore,
    *,
    since_days: int = 10,
) -> CollectionResult:
    items: list[FetchedItem] = []
    errors: list[str] = []

    for query in config.google_news_queries:
        try:
            items.extend(fetch_google_news(query))
        except Exception as exc:  # noqa: BLE001 - continue collecting other sources.
            errors.append(f"Google News query failed: {query}: {exc}")

    for source in config.google_news_sources:
        try:
            items.extend(fetch_google_news_source(source))
        except Exception as exc:  # noqa: BLE001 - continue collecting other sources.
            errors.append(f"Google News source failed: {source.name}: {exc}")

    for source in config.page_sources:
        try:
            items.extend(fetch_page_links(source))
        except Exception as exc:  # noqa: BLE001 - continue collecting other sources.
            errors.append(f"Page source failed: {source.name}: {exc}")

    threshold = datetime.now(UTC) - timedelta(days=since_days)
    matched = 0
    stored_new = 0
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    excluded_urls = {normalize_url(url) for url in config.exclude_urls}

    for item in items:
        if should_exclude_item(config, item, excluded_urls):
            continue
        if item.url in seen_urls:
            continue
        seen_urls.add(item.url)
        fingerprint = title_fingerprint(item.title)
        if fingerprint in seen_titles:
            continue
        seen_titles.add(fingerprint)
        if item.source_type != "page" and item.published_at and item.published_at < threshold:
            continue

        prepared_item = prepare_item(config, item)
        if prepared_item is None:
            continue
        scored = with_deadline(score_item(config, prepared_item))
        if scored.score < config.minimum_score:
            continue
        if scored.primary_category == "公募・補助金・プロポーザル" and not is_public_item_to_keep(scored):
            continue
        matched += 1
        if store.upsert_scored_item(scored):
            stored_new += 1

    return CollectionResult(
        fetched=len(items),
        matched=matched,
        stored_new=stored_new,
        errors=errors,
    )


def with_deadline(scored: ScoredItem) -> ScoredItem:
    text = f"{scored.item.title}\n{scored.item.summary}"
    deadline = extract_deadline(text)
    return replace(scored, deadline_at=deadline.isoformat() if deadline else None)


def should_fetch_detail(scored: ScoredItem) -> bool:
    if scored.deadline_at:
        return False
    if scored.item.source_type != "page":
        return False
    return scored.primary_category == "公募・補助金・プロポーザル"


def prepare_item(config: WatchConfig, item: FetchedItem) -> FetchedItem | None:
    if item.source_type != "page":
        return item
    if is_generic_link_title(config, item.title):
        return None
    if (
        item.source_name in OFFICIAL_PUBLIC_SOURCES
        and has_strong_public_signal(item.title)
        and not has_domain_relevance(f"{item.title}\n{item.summary}")
    ):
        return None

    try:
        detail_text = fetch_page_text(item.url)
    except Exception:
        return item

    detail_summary = summarize_detail(detail_text, source_url=source_page_url(item.summary))
    detail_item = replace(item, summary=detail_summary)
    scored = score_item(config, detail_item)
    if scored.score < config.minimum_score:
        return None
    if (
        scored.primary_category == "公募・補助金・プロポーザル"
        and item.source_name == "文化庁 公募情報"
        and not has_domain_relevance(detail_item.title)
    ):
        return None
    if scored.primary_category == "公募・補助金・プロポーザル" and not has_domain_relevance(
        f"{detail_item.title}\n{detail_item.summary}"
    ):
        return None
    deadline = extract_deadline(detail_text)
    if deadline:
        excerpt = deadline_excerpt(detail_text, deadline.isoformat())
        if excerpt and excerpt not in detail_summary:
            detail_summary = f"{detail_summary} / {excerpt}"
    return replace(detail_item, summary=detail_summary)


def enrich_from_detail_page(scored: ScoredItem) -> ScoredItem:
    try:
        detail_text = fetch_page_text(scored.item.url)
    except Exception:
        return scored

    deadline = extract_deadline(detail_text)
    if not deadline:
        return scored

    summary = scored.item.summary
    excerpt = deadline_excerpt(detail_text, deadline.isoformat())
    if excerpt:
        summary = f"{summary} / {excerpt}" if summary else excerpt
    return replace(
        scored,
        item=replace(scored.item, summary=summary),
        deadline_at=deadline.isoformat(),
    )


def deadline_excerpt(text: str, iso_date: str) -> str:
    year, month, day = iso_date.split("-")
    patterns = [
        f"{int(year)}年{int(month)}月{int(day)}日",
        f"{year}/{int(month)}/{int(day)}",
        f"{int(month)}月{int(day)}日",
    ]
    for pattern in patterns:
        index = text.find(pattern)
        if index >= 0:
            start = max(0, index - 42)
            end = min(len(text), index + 70)
            return text[start:end]
    return ""


def should_exclude_item(
    config: WatchConfig,
    item: FetchedItem,
    excluded_urls: set[str],
) -> bool:
    if normalize_url(item.url) in excluded_urls:
        return True
    return any(
        re.search(pattern, item.title)
        for pattern in config.exclude_title_patterns
    )


def is_generic_link_title(config: WatchConfig, title: str) -> bool:
    return any(
        re.search(pattern, title)
        for pattern in config.generic_link_title_patterns
    )


def normalize_url(url: str) -> str:
    return url.rstrip("/")


def source_page_url(summary: str) -> str:
    match = re.search(r"Source page:\s*(https?://\S+)", summary)
    return match.group(1) if match else ""


def has_domain_relevance(text: str) -> bool:
    return any(term in text for term in DOMAIN_RELEVANCE_TERMS)


def is_public_item_to_keep(scored: ScoredItem) -> bool:
    text = f"{scored.item.title}\n{scored.item.summary}"
    if not has_domain_relevance(text):
        return False
    if scored.item.source_type != "google_news":
        return True
    return any(
        term in text
        for term in [
            "公募",
            "補助",
            "補助金",
            "助成",
            "委託",
            "委託事業",
            "プロポーザル",
            "企画競争",
            "交付金",
            "入札",
            "調達",
        ]
    )
