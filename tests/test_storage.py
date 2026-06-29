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


if __name__ == "__main__":
    unittest.main()
