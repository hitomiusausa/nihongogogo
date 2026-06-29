import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nihongo_funding_watch import pipeline
from nihongo_funding_watch.config import WatchConfig
from nihongo_funding_watch.fetchers import FetchedItem
from nihongo_funding_watch.pipeline import (
    has_domain_relevance,
    normalize_url,
    run_collection,
    source_page_url,
)
from nihongo_funding_watch.storage import WatchStore


def make_config() -> WatchConfig:
    return WatchConfig(
        minimum_score=3,
        google_news_queries=["q"],
        google_news_sources=[],
        page_sources=[],
        exclude_urls=[],
        exclude_title_patterns=[],
        generic_link_title_patterns=[],
        categories={"ニュース（日本語教育）": ["日本語教育"]},
        keyword_weights={"日本語教育": 4},
        sales_angles={},
    )


def make_item(url: str) -> FetchedItem:
    return FetchedItem(
        title="日本語教育の最新ニュース",
        url=url,
        source_name="Google News: q",
        source_type="google_news",
        summary="日本語教育に関する記事です",
    )


class PipelineHelpersTest(unittest.TestCase):
    def test_normalize_url_strips_trailing_slash(self):
        self.assertEqual(normalize_url("https://e.com/a/"), "https://e.com/a")

    def test_source_page_url_extracts_url(self):
        self.assertEqual(
            source_page_url("Source page: https://e.com/p / 概要"),
            "https://e.com/p",
        )
        self.assertEqual(source_page_url("no url here"), "")

    def test_has_domain_relevance(self):
        self.assertTrue(has_domain_relevance("日本語教育の補助金"))
        self.assertFalse(has_domain_relevance("まったく無関係な内容"))


class RunCollectionTest(unittest.TestCase):
    def test_stores_matched_items_and_dedupes_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchStore(Path(tmp) / "w.sqlite3")
            store.initialize()
            with mock.patch.object(pipeline, "fetch_google_news", return_value=[make_item("https://e.com/a")]):
                first = run_collection(make_config(), store, since_days=14)
                second = run_collection(make_config(), store, since_days=14)

            self.assertEqual(first.fetched, 1)
            self.assertEqual(first.matched, 1)
            self.assertEqual(first.stored_new, 1)
            self.assertEqual(first.errors, [])
            # Same URL on the second run must not create a new row.
            self.assertEqual(second.stored_new, 0)
            self.assertEqual(len(store.all_items()), 1)

    def test_fetch_errors_are_captured_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WatchStore(Path(tmp) / "w.sqlite3")
            store.initialize()
            with mock.patch.object(pipeline, "fetch_google_news", side_effect=RuntimeError("boom")):
                result = run_collection(make_config(), store, since_days=14)

            self.assertEqual(result.fetched, 0)
            self.assertEqual(len(result.errors), 1)
            self.assertIn("boom", result.errors[0])


if __name__ == "__main__":
    unittest.main()
