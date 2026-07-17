import unittest
from datetime import datetime, timedelta, timezone

from nihongo_funding_watch.config import WatchConfig
from nihongo_funding_watch.site import (
    JST,
    linkify_html,
    render_card,
    safe_url,
    sort_for_display,
    split_amount,
    truncate,
)
from nihongo_funding_watch.storage import StoredItem


def make_stored_item(
    item_id: int,
    *,
    title: str = "テスト案件",
    deadline_at: str | None = None,
    score: int = 5,
    fetched_at: str | None = None,
    first_seen_at: str | None = None,
) -> StoredItem:
    return StoredItem(
        id=item_id,
        title=title,
        url=f"https://example.com/{item_id}",
        source_name="test",
        source_type="page",
        published_at=None,
        fetched_at=fetched_at or "2026-07-01T00:00:00+00:00",
        summary="",
        primary_category="公募・補助金・プロポーザル",
        categories=["公募・補助金・プロポーザル"],
        score=score,
        matched_keywords=[],
        deadline_at=deadline_at,
        first_seen_at=first_seen_at,
    )


def make_config() -> WatchConfig:
    return WatchConfig(
        minimum_score=3,
        google_news_queries=[],
        google_news_sources=[],
        page_sources=[],
        exclude_urls=[],
        exclude_title_patterns=[],
        generic_link_title_patterns=[],
        categories={},
        keyword_weights={},
        sales_angles={},
    )


class SiteTest(unittest.TestCase):
    def test_safe_url_allows_http_and_https(self):
        self.assertEqual(safe_url("https://example.com/a"), "https://example.com/a")
        self.assertEqual(safe_url("http://example.com/a"), "http://example.com/a")

    def test_safe_url_neutralizes_dangerous_schemes(self):
        self.assertEqual(safe_url("javascript:alert(1)"), "#")
        self.assertEqual(safe_url("data:text/html,<script>"), "#")
        self.assertEqual(safe_url(""), "#")

    def test_linkify_escapes_then_links_only_http(self):
        result = linkify_html("見る https://example.com/x <tag>")
        self.assertIn('<a href="https://example.com/x"', result)
        # The stray angle bracket must be escaped, not rendered as a tag.
        self.assertIn("&lt;tag&gt;", result)

    def test_truncate(self):
        self.assertEqual(truncate("abc", 5), "abc")
        self.assertEqual(truncate("abcdef", 4), "abc…")

    def test_split_amount_extracts_and_removes_segment(self):
        summary, amount = split_amount(
            "Source page: https://e.com/p / 概要文 / 金額: 上限300万円・補助率1／2"
        )
        self.assertEqual(amount, "上限300万円・補助率1／2")
        self.assertEqual(summary, "Source page: https://e.com/p / 概要文")
        summary2, amount2 = split_amount("概要 / 金額: 上限100万円 / 締切: 8月1日")
        self.assertEqual(amount2, "上限100万円")
        self.assertEqual(summary2, "概要 / 締切: 8月1日")

    def test_split_amount_without_amount(self):
        summary, amount = split_amount("ただの概要")
        self.assertEqual((summary, amount), ("ただの概要", ""))


class SortForDisplayTest(unittest.TestCase):
    def test_public_category_orders_active_deadlines_first_ascending(self):
        today = datetime.now(JST).date()
        soon = (today + timedelta(days=3)).isoformat()
        later = (today + timedelta(days=20)).isoformat()
        past = (today - timedelta(days=5)).isoformat()
        items = [
            make_stored_item(1, deadline_at=None, score=9),
            make_stored_item(2, deadline_at=later, score=1),
            make_stored_item(3, deadline_at=past, score=8),
            make_stored_item(4, deadline_at=soon, score=1),
        ]

        ordered = sort_for_display("公募・補助金・プロポーザル", items)

        # 締切が近い順 → 締切なし(スコア順) → 終了
        self.assertEqual([item.id for item in ordered], [4, 2, 1, 3])

    def test_other_categories_keep_input_order(self):
        items = [
            make_stored_item(1, score=1),
            make_stored_item(2, score=9),
        ]

        ordered = sort_for_display("ニュース（日本語教育）", items)

        self.assertEqual([item.id for item in ordered], [1, 2])


class NewBadgeTest(unittest.TestCase):
    def test_item_first_seen_today_gets_new_badge(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        card = render_card(make_config(), make_stored_item(1, first_seen_at=now_iso))
        self.assertIn("本日反映", card)
        self.assertIn('data-new="true"', card)

    def test_item_refetched_today_but_seen_earlier_has_no_new_badge(self):
        # fetched_at は毎日の再取得で今日になるが、初出が過去ならNEWではない
        now_iso = datetime.now(timezone.utc).isoformat()
        card = render_card(
            make_config(),
            make_stored_item(
                1, fetched_at=now_iso, first_seen_at="2026-07-01T00:00:00+00:00"
            ),
        )
        self.assertNotIn("本日反映", card)
        self.assertIn('data-new="false"', card)


if __name__ == "__main__":
    unittest.main()
