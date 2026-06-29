from __future__ import annotations

from dataclasses import dataclass

from .config import WatchConfig
from .fetchers import FetchedItem


@dataclass(frozen=True)
class ScoredItem:
    item: FetchedItem
    score: int
    categories: list[str]
    matched_keywords: list[str]
    primary_category: str
    deadline_at: str | None = None


def score_item(config: WatchConfig, item: FetchedItem) -> ScoredItem:
    title_text = item.title.lower()
    text = f"{item.title}\n{item.summary}".lower()
    page_without_public_title = (
        item.source_type == "page" and not has_strong_public_signal(title_text)
    )
    matched: list[str] = []
    score = 0

    for keyword, weight in config.keyword_weights.items():
        if page_without_public_title and is_public_keyword(keyword):
            continue
        if keyword.lower() in text:
            matched.append(keyword)
            score += weight

    categories: list[str] = []
    for category, terms in config.categories.items():
        if category == "公募・補助金・プロポーザル" and page_without_public_title:
            continue
        if any(term.lower() in text for term in terms):
            categories.append(category)

    if not categories and matched:
        categories.append("その他")

    primary = choose_primary_category(categories, text, title_text=title_text)
    return ScoredItem(
        item=item,
        score=score,
        categories=categories,
        matched_keywords=matched,
        primary_category=primary,
    )


def choose_primary_category(
    categories: list[str],
    text: str = "",
    *,
    title_text: str = "",
) -> str:
    public_signal_text = title_text or text
    if (
        "公募・補助金・プロポーザル" in categories
        and has_strong_public_signal(public_signal_text)
    ):
        return "公募・補助金・プロポーザル"

    priority = [
        "ニュース（外国人・ビザ）",
        "ニュース（日本語教育）",
        "公募・補助金・プロポーザル",
        "その他",
    ]
    for category in priority:
        if category in categories:
            return category
    return categories[0] if categories else "その他"


def has_strong_public_signal(text: str) -> bool:
    return any(
        term.lower() in text
        for term in [
            "公募",
            "募集",
            "企画競争",
            "プロポーザル",
            "委託事業",
            "補助金",
            "補助",
            "助成",
            "交付金",
            "入札",
            "調達",
            "総合評価落札方式",
        ]
    )


def is_public_keyword(keyword: str) -> bool:
    return keyword in {
        "公募",
        "プロポーザル",
        "企画競争",
        "委託事業",
        "委託",
        "補助金",
        "補助",
        "助成",
        "交付金",
    }
