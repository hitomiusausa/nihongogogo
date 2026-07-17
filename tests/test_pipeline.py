import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nihongo_funding_watch import pipeline
from nihongo_funding_watch.config import WatchConfig
from nihongo_funding_watch.fetchers import FetchedItem, HttpStatusError
from nihongo_funding_watch.pipeline import (
    check_links,
    has_domain_relevance,
    normalize_url,
    prepare_item,
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


def make_page_item(url: str) -> FetchedItem:
    return FetchedItem(
        title="日本語教育 補助金のご案内",
        url=url,
        source_name="自治体テスト",
        source_type="page",
        summary="Source page: https://example.com/list",
    )


class PrepareItemDeadLinkTest(unittest.TestCase):
    def test_dropped_when_detail_page_is_gone(self):
        item = make_page_item("https://example.com/removed.html")
        with mock.patch.object(
            pipeline,
            "fetch_page_text",
            side_effect=HttpStatusError(404, item.url),
        ):
            self.assertIsNone(prepare_item(make_config(), item))

    def test_kept_when_detail_fetch_fails_transiently(self):
        item = make_page_item("https://example.com/slow.html")
        with mock.patch.object(
            pipeline, "fetch_page_text", side_effect=RuntimeError("timeout")
        ):
            self.assertIs(prepare_item(make_config(), item), item)

    def test_kept_when_detail_fetch_fails_with_server_error(self):
        item = make_page_item("https://example.com/error.html")
        with mock.patch.object(
            pipeline,
            "fetch_page_text",
            side_effect=HttpStatusError(500, item.url),
        ):
            self.assertIs(prepare_item(make_config(), item), item)


class CheckLinksTest(unittest.TestCase):
    def _store_with_urls(self, tmp: str, urls: list[str]) -> WatchStore:
        store = WatchStore(Path(tmp) / "w.sqlite3")
        store.initialize()
        items = [
            FetchedItem(
                title=f"日本語教育のニュース その{index}",
                url=url,
                source_name="Google News: q",
                source_type="google_news",
                summary="日本語教育に関する記事です",
            )
            for index, url in enumerate(urls)
        ]
        with mock.patch.object(pipeline, "fetch_google_news", return_value=items):
            run_collection(make_config(), store, since_days=14)
        return store

    def test_marks_dead_links_and_revives_recovered_ones(self):
        dead_url = "https://example.com/dead"
        alive_url = "https://example.com/alive"
        google_url = "https://news.google.com/rss/articles/abc?oc=5"
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store_with_urls(tmp, [dead_url, alive_url, google_url])

            def fake_get(url, **kwargs):
                if url == dead_url:
                    raise HttpStatusError(404, url)
                if "news.google.com" in url:
                    raise AssertionError("Google Newsリンクは検査対象外のはず")
                return b"ok"

            with mock.patch.object(pipeline, "http_get", side_effect=fake_get):
                result = check_links(store, since_days=14)

            self.assertEqual(result.marked_dead, 1)
            visible_urls = {item.url for item in store.recent_items(since_days=14)}
            self.assertNotIn(dead_url, visible_urls)
            self.assertIn(alive_url, visible_urls)
            self.assertIn(google_url, visible_urls)
            # 履歴（all_items）からは消えない
            self.assertIn(dead_url, {item.url for item in store.all_items()})

            # ページ復活後は再掲載される
            with mock.patch.object(pipeline, "http_get", return_value=b"ok"):
                check_links(store, since_days=14)
            self.assertIn(
                dead_url, {item.url for item in store.recent_items(since_days=14)}
            )

    def test_transient_errors_do_not_mark_dead(self):
        url = "https://example.com/flaky"
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store_with_urls(tmp, [url])
            with mock.patch.object(
                pipeline, "http_get", side_effect=RuntimeError("timeout")
            ):
                result = check_links(store, since_days=14)
            self.assertEqual(result.marked_dead, 0)
            self.assertIn(url, {item.url for item in store.recent_items(since_days=14)})


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
