from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from .config import WatchConfig
from .deadlines import days_until, parse_iso_date
from .fetchers import title_fingerprint
from .storage import StoredItem, WatchStore


JST = ZoneInfo("Asia/Tokyo")
CATEGORY_ORDER = [
    "公募・補助金・プロポーザル",
    "ニュース（日本語教育）",
    "ニュース（外国人・ビザ）",
    "その他",
]
ARCHIVE_AFTER_DAYS = 180


def write_report(
    config: WatchConfig,
    store: WatchStore,
    report_dir: Path,
    *,
    since_days: int = 10,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(JST).date().isoformat()
    path = report_dir / f"{today}.md"
    items = dedupe_items(store.recent_items(since_days=since_days))
    path.write_text(render_report(config, items, since_days=since_days), encoding="utf-8")
    return path


def render_report(
    config: WatchConfig,
    items: list[StoredItem],
    *,
    since_days: int = 10,
) -> str:
    now = datetime.now(JST)
    today = now.date()
    visible_items = [
        item
        for item in items
        if not is_archived(item, today=today)
    ]
    active_items = [
        item
        for item in visible_items
        if not is_expired(item, today=today)
    ]
    expired_items = [
        item
        for item in visible_items
        if is_expired(item, today=today)
    ]
    grouped: dict[str, list[StoredItem]] = defaultdict(list)
    for item in active_items:
        grouped[item.primary_category].append(item)

    lines = [
        f"# 日本語教育 資金・政策ウォッチ ({now.date().isoformat()})",
        "",
        f"- 作成時刻: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- 対象期間: 直近{since_days}日",
        f"- 候補件数: {len(visible_items)}",
        f"- 終了案件: {len(expired_items)}",
    ]
    lines.append("")

    for category in CATEGORY_ORDER:
        category_items = grouped.get(category, [])
        if not category_items:
            continue
        lines.extend([f"## {category}", ""])
        for item in category_items[:25]:
            lines.extend(render_item(item, config))
        lines.append("")

    if expired_items:
        lines.extend(["## 終了案件", ""])
        for item in sorted(expired_items, key=expired_sort_key)[:30]:
            lines.extend(render_item(item, config))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_item(item: StoredItem, config: WatchConfig, *, compact: bool = False) -> list[str]:
    keywords = ", ".join(item.matched_keywords[:8]) if item.matched_keywords else "-"
    angle = config.sales_angles.get(item.primary_category, "")
    published = item.published_at or "日付不明"
    deadline = parse_iso_date(item.deadline_at)
    remaining = days_until(deadline)
    deadline_text = format_deadline(deadline, remaining)
    reflected = format_datetime_date(item.fetched_at)

    lines = [
        f"- [{item.title}]({item.url})",
        f"  - 分類: {item.primary_category} / 国: {item.country or '-'} / スコア: {item.score} / 出典: {item.source_name}",
        f"  - 公開日: {published} / ページ反映日: {reflected} / 締切: {deadline_text} / キーワード: {keywords}",
    ]
    if not compact and item.summary:
        lines.append(f"  - 概要: {linkify_markdown(truncate(item.summary, 180))}")
    if angle:
        lines.append(f"  - Nihongo Catch! 提案切り口: {angle}")
    return lines


def truncate(value: str, max_length: int) -> str:
    return value if len(value) <= max_length else value[: max_length - 1] + "…"


def linkify_markdown(value: str) -> str:
    return re.sub(r"(https?://[^\s)]+)", r"[\1](\1)", value)


def format_deadline(deadline, remaining: int | None) -> str:
    if not deadline or remaining is None:
        return "未検出"
    if remaining < 0:
        label = "終了直後" if remaining >= -30 else "終了案件"
        return f"{deadline.isoformat()} ({label} / {abs(remaining)}日前)"
    return f"{deadline.isoformat()} ({remaining}日後)"


def format_datetime_date(value: str | None) -> str:
    if not value:
        return "日付不明"
    try:
        return datetime.fromisoformat(value).astimezone(JST).date().isoformat()
    except ValueError:
        return value


def dedupe_items(items: list[StoredItem]) -> list[StoredItem]:
    deduped: list[StoredItem] = []
    seen: set[str] = set()
    for item in items:
        key = title_fingerprint(item.title)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def is_expired(item: StoredItem, *, today: date) -> bool:
    remaining = days_until(parse_iso_date(item.deadline_at), today=today)
    return remaining is not None and remaining < 0


def is_archived(item: StoredItem, *, today: date) -> bool:
    remaining = days_until(parse_iso_date(item.deadline_at), today=today)
    return remaining is not None and remaining < -ARCHIVE_AFTER_DAYS


def expired_sort_key(item: StoredItem) -> int:
    remaining = days_until(parse_iso_date(item.deadline_at))
    return abs(remaining) if remaining is not None else 9999
