import tempfile
import unittest
from pathlib import Path

from nihongo_funding_watch.fetchers import FetchedItem
from nihongo_funding_watch.scoring import ScoredItem
from nihongo_funding_watch.storage import WatchStore


class StorageTest(unittest.TestCase):
    def test_upsert_deduplicates_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchStore(Path(tmp) / "watch.sqlite3")
            store.initialize()
            scored = ScoredItem(
                item=FetchedItem(
                    title="日本語教育 補助金",
                    url="https://example.com/a",
                    source_name="test",
                    source_type="test",
                    country="インドネシア",
                ),
                score=9,
                categories=["公募・補助金・プロポーザル"],
                matched_keywords=["日本語教育", "補助金"],
                primary_category="公募・補助金・プロポーザル",
            )

            self.assertTrue(store.upsert_scored_item(scored))
            self.assertFalse(store.upsert_scored_item(scored))

            items = store.all_items()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].score, 9)
            self.assertEqual(items[0].country, "インドネシア")


    def test_upsert_deduplicates_wave_dash_title_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchStore(Path(tmp) / "watch.sqlite3")
            store.initialize()

            def scored(title: str, url: str) -> ScoredItem:
                return ScoredItem(
                    item=FetchedItem(
                        title=title,
                        url=url,
                        source_name="test",
                        source_type="google_news",
                    ),
                    score=5,
                    categories=["ニュース（日本語教育）"],
                    matched_keywords=["日本語教育"],
                    primary_category="ニュース（日本語教育）",
                )

            self.assertTrue(
                store.upsert_scored_item(scored("研修の応募開始 ～教師を育成～", "https://example.com/a"))
            )
            self.assertFalse(
                store.upsert_scored_item(scored("研修の応募開始 〜教師を育成〜", "https://example.com/b"))
            )
            self.assertEqual(len(store.all_items()), 1)

    def test_first_seen_at_is_set_on_insert_and_preserved_on_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchStore(Path(tmp) / "watch.sqlite3")
            store.initialize()
            scored = ScoredItem(
                item=FetchedItem(
                    title="日本語教育 補助金",
                    url="https://example.com/a",
                    source_name="test",
                    source_type="page",
                ),
                score=5,
                categories=["公募・補助金・プロポーザル"],
                matched_keywords=["日本語教育"],
                primary_category="公募・補助金・プロポーザル",
            )
            store.upsert_scored_item(scored)
            first = store.all_items()[0].first_seen_at
            self.assertIsNotNone(first)

            # 初出日を過去に固定し、再取得(upsert)後も動かないことを確認
            import sqlite3
            with sqlite3.connect(store.db_path) as db:
                db.execute("UPDATE items SET first_seen_at = '2026-07-01T00:00:00+00:00'")
            store.upsert_scored_item(scored)
            self.assertEqual(
                store.all_items()[0].first_seen_at, "2026-07-01T00:00:00+00:00"
            )

    def test_mark_dead_hides_item_from_recent_but_keeps_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchStore(Path(tmp) / "watch.sqlite3")
            store.initialize()
            scored = ScoredItem(
                item=FetchedItem(
                    title="日本語教育 補助金",
                    url="https://example.com/a",
                    source_name="test",
                    source_type="page",
                ),
                score=9,
                categories=["公募・補助金・プロポーザル"],
                matched_keywords=["日本語教育"],
                primary_category="公募・補助金・プロポーザル",
            )
            store.upsert_scored_item(scored)

            store.mark_dead("https://example.com/a")
            self.assertEqual(store.recent_items(since_days=14), [])
            self.assertEqual(len(store.recent_items(since_days=14, include_dead=True)), 1)
            self.assertEqual(len(store.all_items()), 1)

            store.clear_dead("https://example.com/a")
            self.assertEqual(len(store.recent_items(since_days=14)), 1)


if __name__ == "__main__":
    unittest.main()
