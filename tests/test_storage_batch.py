import sqlite3
import tempfile
import unittest
from pathlib import Path

from nihongo_funding_watch.fetchers import FetchedItem
from nihongo_funding_watch.scoring import ScoredItem
from nihongo_funding_watch.storage import SCHEMA_VERSION, WatchStore


def scored(url: str, title: str = "日本語教育 補助金", score: int = 5) -> ScoredItem:
    return ScoredItem(
        item=FetchedItem(title=title, url=url, source_name="t", source_type="t"),
        score=score,
        categories=["公募・補助金・プロポーザル"],
        matched_keywords=["補助金"],
        primary_category="公募・補助金・プロポーザル",
    )


class StorageBatchTest(unittest.TestCase):
    def test_batch_upsert_counts_only_new_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchStore(Path(tmp) / "w.sqlite3")
            store.initialize()
            stored_new = store.upsert_scored_items(
                [scored("https://e.com/a", "記事A"), scored("https://e.com/b", "記事B")]
            )
            self.assertEqual(stored_new, 2)
            # Re-inserting the same URLs adds nothing new.
            stored_again = store.upsert_scored_items(
                [scored("https://e.com/a", "記事A"), scored("https://e.com/c", "記事C")]
            )
            self.assertEqual(stored_again, 1)
            self.assertEqual(len(store.all_items()), 3)

    def test_initialize_sets_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "w.sqlite3"
            store = WatchStore(db_path)
            store.initialize()
            # Calling initialize again should be safe (idempotent).
            store.initialize()
            conn = sqlite3.connect(db_path)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            conn.close()
            self.assertEqual(version, SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
