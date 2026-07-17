import tempfile
import unittest
from pathlib import Path

from nihongo_funding_watch.config import WatchConfig
from nihongo_funding_watch.fetchers import FetchedItem
from nihongo_funding_watch.report import (
    dedupe_items,
    group_items,
    select_display_items,
)
from nihongo_funding_watch.scoring import ScoredItem
from nihongo_funding_watch.storage import StoredItem, WatchStore


def make_item(item_id: int, title: str, url: str) -> StoredItem:
    return StoredItem(
        id=item_id,
        title=title,
        url=url,
        source_name="test",
        source_type="google_news",
        published_at=None,
        fetched_at="2026-07-17T00:00:00+00:00",
        summary="",
        primary_category="ニュース（日本語教育）",
        categories=["ニュース（日本語教育）"],
        score=5,
        matched_keywords=[],
    )


class DedupeItemsTest(unittest.TestCase):
    def test_collapses_wave_dash_and_truncation_variants(self):
        # 実データ: 2026-07-17の公開ページに同一プレスリリースが4カード並んだ
        items = [
            make_item(
                1,
                "文部科学省委託「子どものための日本語教育研修」応募受付開始 ～外国人児童生徒支援に携わる日本語教師を育成～",
                "https://example.com/1",
            ),
            make_item(
                2,
                "文部科学省委託「子どものための日本語教育研修」応募受付開始 〜外国人児童生徒支援に携わる日本語教師を育成〜",
                "https://example.com/2",
            ),
            make_item(
                3,
                "文部科学省委託「子どものための日本語教育研修」応募受付開始 ～外国人児童生徒支援に携わる日本語教師を育成",
                "https://example.com/3",
            ),
            make_item(
                4,
                "文部科学省委託「子どものための日本語教育研修」応募受付開始 ～外国人児童生徒..（認定NPO法人メタノイア プレスリリース）",
                "https://example.com/4",
            ),
        ]

        deduped = dedupe_items(items)

        self.assertEqual([item.id for item in deduped], [1])

    def test_keeps_first_item_when_collapsing_outlet_variants(self):
        items = [
            make_item(
                1,
                "明光ネットワークジャパンの子会社、明光キャリアパートナーズ 令和8年度広島県「外国人材日本語学習支援業務」を受託",
                "https://example.com/a",
            ),
            make_item(
                2,
                "株式会社明光キャリアパートナーズ 令和8年度広島県「外国人材日本語学習支援業務」を受託",
                "https://example.com/b",
            ),
        ]

        deduped = dedupe_items(items)

        self.assertEqual([item.id for item in deduped], [1])

    def test_keeps_distinct_announcements(self):
        items = [
            make_item(1, "岐阜県外国人介護人材日本語学習支援事業費補助金", "https://example.com/gifu"),
            make_item(2, "令和８年度福岡県外国人介護人材確保強化事業費補助金", "https://example.com/fukuoka"),
            make_item(3, "神奈川県高度外国人材受入支援補助金", "https://example.com/kanagawa"),
        ]

        deduped = dedupe_items(items)

        self.assertEqual(len(deduped), 3)


class GroupItemsTest(unittest.TestCase):
    def test_duplicates_are_attached_as_related_not_dropped(self):
        items = [
            make_item(
                1,
                "明光ネットワークジャパンの子会社、明光キャリアパートナーズ 令和8年度広島県「外国人材日本語学習支援業務」を受託",
                "https://example.com/a",
            ),
            make_item(
                2,
                "株式会社明光キャリアパートナーズ 令和8年度広島県「外国人材日本語学習支援業務」を受託",
                "https://example.com/b",
            ),
            make_item(3, "別のニュースです 日本語教育の新制度", "https://example.com/c"),
        ]

        groups = group_items(items)

        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0].item.id, 1)
        self.assertEqual([related.id for related in groups[0].related], [2])
        self.assertEqual(groups[1].related, [])


class DeadItemsRemainListedTest(unittest.TestCase):
    def test_dead_marked_items_stay_in_display_as_record(self):
        config = WatchConfig(
            minimum_score=3,
            google_news_queries=[],
            google_news_sources=[],
            page_sources=[],
            exclude_urls=[],
            exclude_title_patterns=[],
            generic_link_title_patterns=[],
            categories={"公募・補助金・プロポーザル": ["補助金"]},
            keyword_weights={"補助金": 4},
            sales_angles={},
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchStore(Path(tmp) / "w.sqlite3")
            store.initialize()
            store.upsert_scored_item(
                ScoredItem(
                    item=FetchedItem(
                        title="日本語教育支援補助金",
                        url="https://example.com/removed.html",
                        source_name="県",
                        source_type="page",
                    ),
                    score=5,
                    categories=["公募・補助金・プロポーザル"],
                    matched_keywords=["補助金"],
                    primary_category="公募・補助金・プロポーザル",
                )
            )
            store.mark_dead("https://example.com/removed.html")

            items = select_display_items(config, store, since_days=14)

            # リンク切れでも記録として一覧に残る（表示側でリンク切れ表記が付く）
            self.assertEqual(len(items), 1)
            self.assertIsNotNone(items[0].dead_at)


class SelectDisplayItemsTest(unittest.TestCase):
    def test_excluded_urls_are_hidden_even_if_already_stored(self):
        config = WatchConfig(
            minimum_score=3,
            google_news_queries=[],
            google_news_sources=[],
            page_sources=[],
            exclude_urls=["https://www.moj.go.jp/isa/08_00045.html"],
            exclude_title_patterns=[],
            generic_link_title_patterns=[],
            categories={"ニュース（外国人・ビザ）": ["在留資格"]},
            keyword_weights={"在留資格": 4},
            sales_angles={},
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchStore(Path(tmp) / "w.sqlite3")
            store.initialize()
            for title, url in [
                ("監理措置制度", "https://www.moj.go.jp/isa/08_00045.html"),
                ("在留資格の改正について", "https://www.moj.go.jp/isa/10_00999.html"),
            ]:
                store.upsert_scored_item(
                    ScoredItem(
                        item=FetchedItem(
                            title=title,
                            url=url,
                            source_name="出入国在留管理庁",
                            source_type="page",
                        ),
                        score=5,
                        categories=["ニュース（外国人・ビザ）"],
                        matched_keywords=["在留資格"],
                        primary_category="ニュース（外国人・ビザ）",
                    )
                )

            titles = [item.title for item in select_display_items(config, store, since_days=14)]

            self.assertEqual(titles, ["在留資格の改正について"])


if __name__ == "__main__":
    unittest.main()
