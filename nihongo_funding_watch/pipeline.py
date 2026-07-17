from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time
import urllib.parse

from .amounts import extract_amount
from .config import WatchConfig
from .deadlines import extract_deadline
from .fetchers import (
    FetchedItem,
    HttpStatusError,
    fetch_google_news,
    fetch_google_news_source,
    fetch_page_links,
    fetch_page_text,
    http_get,
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


DEAD_LINK_STATUS_CODES = {404, 410}


@dataclass(frozen=True)
class CollectionResult:
    fetched: int
    matched: int
    stored_new: int
    errors: list[str]
    source_counts: dict[str, int] = field(default_factory=dict)
    zero_page_sources: list[str] = field(default_factory=list)


def write_health(result: CollectionResult, path: Path) -> None:
    """収集の健康状態を保存する。site/reportが読んで人間に見える場所へ出す。"""
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "fetched": result.fetched,
        "matched": result.matched,
        "stored_new": result.stored_new,
        "errors": result.errors,
        "source_counts": result.source_counts,
        "zero_page_sources": result.zero_page_sources,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def load_health(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


@dataclass(frozen=True)
class LinkCheckResult:
    checked: int
    marked_dead: int
    revived: int


def check_links(
    store: WatchStore,
    *,
    since_days: int = 14,
    pause_seconds: float = 0.1,
) -> LinkCheckResult:
    """表示対象期間のリンクを実査し、消えたページを掲載から外す（復活したら戻す）。

    news.google.com はリダイレクタで常に200を返すため検査対象外。
    404/410 だけを「死んだリンク」とみなし、一時的な障害では掲載を止めない。
    """
    checked = 0
    marked_dead = 0
    revived = 0
    for item in store.recent_items(since_days=since_days, include_dead=True):
        parsed = urllib.parse.urlsplit(item.url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc.endswith("news.google.com"):
            continue
        checked += 1
        try:
            http_get(item.url)
        except HttpStatusError as exc:
            if exc.code in DEAD_LINK_STATUS_CODES and item.dead_at is None:
                store.mark_dead(item.url)
                marked_dead += 1
            continue
        except Exception:
            continue
        finally:
            time.sleep(pause_seconds)
        if item.dead_at is not None:
            store.clear_dead(item.url)
            revived += 1
    return LinkCheckResult(checked=checked, marked_dead=marked_dead, revived=revived)


def run_collection(
    config: WatchConfig,
    store: WatchStore,
    *,
    since_days: int = 10,
) -> CollectionResult:
    items: list[FetchedItem] = []
    errors: list[str] = []
    source_counts: dict[str, int] = {}

    for query in config.google_news_queries:
        try:
            batch = fetch_google_news(query)
            items.extend(batch)
            source_counts[f"Google News: {query}"] = len(batch)
        except Exception as exc:  # noqa: BLE001 - continue collecting other sources.
            errors.append(f"Google News query failed: {query}: {exc}")

    for source in config.google_news_sources:
        try:
            batch = fetch_google_news_source(source)
            items.extend(batch)
            source_counts[f"Google News: {source.name}"] = len(batch)
        except Exception as exc:  # noqa: BLE001 - continue collecting other sources.
            errors.append(f"Google News source failed: {source.name}: {exc}")

    for source in config.page_sources:
        try:
            batch = fetch_page_links(source)
            items.extend(batch)
            source_counts[source.name] = len(batch)
        except Exception as exc:  # noqa: BLE001 - continue collecting other sources.
            errors.append(f"Page source failed: {source.name}: {exc}")

    zero_page_sources = [
        source.name
        for source in config.page_sources
        if source_counts.get(source.name, 0) == 0
    ]

    threshold = datetime.now(timezone.utc) - timedelta(days=since_days)
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    excluded_urls = {normalize_url(url) for url in config.exclude_urls}
    matched_items: list[ScoredItem] = []

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
        matched_items.append(scored)

    stored_new = store.upsert_scored_items(matched_items)

    return CollectionResult(
        fetched=len(items),
        matched=len(matched_items),
        stored_new=stored_new,
        errors=errors,
        source_counts=source_counts,
        zero_page_sources=zero_page_sources,
    )


def with_deadline(scored: ScoredItem) -> ScoredItem:
    text = f"{scored.item.title}\n{scored.item.summary}"
    deadline = extract_deadline(text)
    return replace(scored, deadline_at=deadline.isoformat() if deadline else None)


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
    except HttpStatusError as exc:
        if exc.code in DEAD_LINK_STATUS_CODES:
            # リンク先が消えたページを掲載し続けない。一時的な障害(5xx等)とは区別する。
            return None
        return item
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
    amount = extract_amount(detail_text)
    if amount:
        detail_summary = f"{detail_summary} / 金額: {amount}"
    return replace(detail_item, summary=detail_summary)


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
    return any(regex.search(item.title) for regex in config.exclude_title_regexes)


def is_generic_link_title(config: WatchConfig, title: str) -> bool:
    return any(regex.search(title) for regex in config.generic_link_title_regexes)


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
