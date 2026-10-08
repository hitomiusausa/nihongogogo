import csv
import json
import os
import sqlite3
import tempfile
from contextlib import closing
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from nihongo_funding_watch import ai_enrich
from nihongo_funding_watch.ai_enrich import MODEL, enrich_items
from nihongo_funding_watch.export import export_csv
from nihongo_funding_watch.fetchers import FetchedItem
from nihongo_funding_watch.scoring import ScoredItem
from nihongo_funding_watch.site import render_site
from nihongo_funding_watch.storage import WatchStore

from test_site import make_config, make_stored_item


# ---- anthropic SDK を import せずに例外の型名だけ真似るフェイク -------------------
class APIStatusError(Exception):
    def __init__(self, message: str = "error", request_id: str | None = "req_err") -> None:
        super().__init__(message)
        self.request_id = request_id


class AuthenticationError(APIStatusError):
    pass


class RateLimitError(APIStatusError):
    pass


def text_response(payload: dict, *, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason,
        model=MODEL,
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=json.dumps(payload, ensure_ascii=False)),
        ],
        _request_id="req_ok",
    )


class FakeClient:
    """client.beta.messages.create(**kwargs) を受けて、用意した応答（または例外）を順に返す。"""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def scored(
    title: str,
    url: str,
    *,
    category: str = "公募・補助金・プロポーザル",
    source_type: str = "google_news",
) -> ScoredItem:
    return ScoredItem(
        item=FetchedItem(
            title=title,
            url=url,
            source_name="test",
            source_type=source_type,
            summary="掲載元: テスト新聞",
        ),
        score=7,
        categories=[category],
        matched_keywords=["日本語教育"],
        primary_category=category,
    )


class AiEnrichTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = WatchStore(Path(self.tmp.name) / "watch.sqlite3")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def add(self, *args, **kwargs) -> None:
        self.store.upsert_scored_item(scored(*args, **kwargs))

    def run_enrich(self, client: FakeClient, **kwargs):
        logs: list[str] = []
        with mock.patch.object(ai_enrich, "PAGE_FETCH_PAUSE_SECONDS", 0):
            result = enrich_items(
                self.store,
                client=client,
                page_text_fetcher=kwargs.pop("page_text_fetcher", lambda url: ""),
                log=logs.append,
                **kwargs,
            )
        return result, logs

    def test_success_saves_fields_and_uses_expected_call_shape(self):
        self.add("日本語教育 補助金 公募", "https://example.com/a")
        client = FakeClient(
            [text_response({"summary": "県の日本語教室補助。", "relevance": "高", "sales_hint": "教材として提案"})]
        )

        result, _ = self.run_enrich(client)

        self.assertEqual((result.enriched, result.skipped, result.failed), (1, 0, 0))
        item = self.store.all_items()[0]
        self.assertEqual(item.ai_summary, "県の日本語教室補助。")
        self.assertEqual(item.ai_relevance, "高")
        self.assertEqual(item.ai_sales_hint, "教材として提案")
        self.assertEqual(item.ai_model, MODEL)
        self.assertIsNotNone(item.ai_enriched_at)
        call = client.calls[0]
        self.assertEqual(call["model"], "claude-sonnet-5-5")
        self.assertEqual(call["fallbacks"], "default")
        self.assertEqual(call["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(call["output_config"]["effort"], "medium")
        self.assertEqual(call["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("thinking", call)
        self.assertNotIn("temperature", call)

    def test_sales_hint_cleared_for_non_public_category(self):
        self.add("在留資格の新制度", "https://example.com/n", category="ニュース（外国人・ビザ）")
        client = FakeClient([text_response({"summary": "制度変更。", "relevance": "中", "sales_hint": "提案"})])

        self.run_enrich(client)

        self.assertEqual(self.store.all_items()[0].ai_sales_hint, "")

    def test_refusal_marks_attempted_with_empty_summary(self):
        self.add("日本語教育 補助金", "https://example.com/a")
        client = FakeClient([text_response({}, stop_reason="refusal")])

        result, _ = self.run_enrich(client)

        self.assertEqual((result.enriched, result.skipped), (0, 1))
        item = self.store.all_items()[0]
        self.assertEqual(item.ai_summary, "")
        self.assertIsNone(item.ai_relevance)
        self.assertIsNotNone(item.ai_enriched_at)
        self.assertEqual(self.store.items_needing_enrichment(10), [])

    def test_missing_api_key_skips_without_calling(self):
        self.add("日本語教育 補助金", "https://example.com/a")
        env = {key: value for key, value in os.environ.items() if key != "ANTHROPIC_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True):
            result = enrich_items(self.store)

        self.assertIn("ANTHROPIC_API_KEY", result.skip_reason)
        self.assertEqual(result.enriched, 0)
        self.assertIsNone(self.store.all_items()[0].ai_enriched_at)

    def test_auth_error_aborts_whole_run(self):
        self.add("日本語教育 補助金 1", "https://example.com/1")
        self.add("日本語教育 補助金 2", "https://example.com/2")
        client = FakeClient([AuthenticationError("invalid x-api-key"), text_response({})])

        result, logs = self.run_enrich(client)

        self.assertTrue(result.aborted)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(logs), 1)
        self.assertIn("req_err", logs[0])
        self.assertEqual(len(self.store.items_needing_enrichment(10)), 2)

    def test_rate_limit_leaves_item_unattempted_and_continues(self):
        self.add("日本語教育 補助金 1", "https://example.com/1")
        self.add("日本語教育 補助金 2", "https://example.com/2")
        client = FakeClient(
            [
                RateLimitError("rate limited"),
                text_response({"summary": "要約。", "relevance": "中", "sales_hint": ""}),
            ]
        )

        result, _ = self.run_enrich(client)

        self.assertEqual((result.enriched, result.failed), (1, 1))
        self.assertEqual(len(self.store.items_needing_enrichment(10)), 1)

    def test_page_text_only_for_non_google_news_and_capped(self):
        self.add("日本語教育 補助金 G", "https://news.google.com/rss/articles/x")
        self.add("日本語教育 補助金 P", "https://pref.example.jp/p", source_type="page")
        fetched: list[str] = []

        def fetcher(url: str) -> str:
            fetched.append(url)
            return "本文" * 10000

        client = FakeClient([text_response({"summary": "s", "relevance": "高", "sales_hint": ""})] * 2)
        self.run_enrich(client, page_text_fetcher=fetcher)

        self.assertEqual(fetched, ["https://pref.example.jp/p"])
        page_call = next(c for c in client.calls if "pref.example.jp" in c["messages"][0]["content"])
        self.assertLessEqual(page_call["messages"][0]["content"].count("本文"), ai_enrich.MAX_PAGE_TEXT_CHARS // 2)

    def test_page_fetch_error_still_enriches(self):
        self.add("日本語教育 補助金 P", "https://pref.example.jp/p", source_type="page")

        def broken(url: str) -> str:
            raise RuntimeError("timeout")

        client = FakeClient([text_response({"summary": "s", "relevance": "高", "sales_hint": ""})])
        result, _ = self.run_enrich(client, page_text_fetcher=broken)

        self.assertEqual(result.enriched, 1)

    def test_upsert_does_not_wipe_ai_columns(self):
        self.add("日本語教育 補助金", "https://example.com/a")
        item_id = self.store.all_items()[0].id
        self.store.save_enrichment(item_id, summary="要約", relevance="高", sales_hint="切り口", model=MODEL)

        self.add("日本語教育 補助金", "https://example.com/a")  # 翌日の再取得（同URL）
        self.add("日本語教育 補助金", "https://example.com/other")  # 同タイトル別URL

        items = self.store.all_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].ai_summary, "要約")
        self.assertEqual(items[0].ai_relevance, "高")
        self.assertEqual(items[0].ai_sales_hint, "切り口")

    def test_initialize_adds_ai_columns_to_existing_db(self):
        path = Path(self.tmp.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                """
                CREATE TABLE items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE, source_name TEXT NOT NULL,
                    source_type TEXT NOT NULL, published_at TEXT, fetched_at TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '', primary_category TEXT NOT NULL,
                    categories_json TEXT NOT NULL, score INTEGER NOT NULL,
                    matched_keywords_json TEXT NOT NULL
                )
                """
            )
        store = WatchStore(path)
        store.initialize()
        with closing(sqlite3.connect(path)) as db, db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(items)")}
        self.assertTrue({"ai_summary", "ai_relevance", "ai_sales_hint", "ai_model", "ai_enriched_at"} <= columns)

    def test_csv_has_ai_columns_at_end(self):
        self.add("日本語教育 補助金", "https://example.com/a")
        item_id = self.store.all_items()[0].id
        self.store.save_enrichment(item_id, summary="要約", relevance="高", sales_hint="切り口", model=MODEL)
        output = Path(self.tmp.name) / "items.csv"

        export_csv(self.store, output)

        with output.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[0][-4:], ["summary", "ai_summary", "ai_relevance", "ai_sales_hint"])
        self.assertEqual(rows[1][-3:], ["要約", "高", "切り口"])


class AiSiteTest(unittest.TestCase):
    def test_irrelevant_hidden_by_default_with_toggle(self):
        from dataclasses import replace

        relevant = replace(
            make_stored_item(1, title="日本語教室の補助金"),
            ai_summary="県が<b>日本語教室</b>を補助。",
            ai_relevance="高",
            ai_sales_hint="教材として提案",
        )
        irrelevant = replace(make_stored_item(2, title="全国旅行支援まとめ"), ai_summary="旅行割引。", ai_relevance="無関係")
        plain = make_stored_item(3, title="未処理の記事")

        html = render_site(make_config(), [relevant, irrelevant, plain])

        self.assertIn("AIが無関係と判定した記事も表示（1件）", html)
        self.assertIn('data-ai-irrelevant="true" hidden>', html)
        self.assertIn("AI要約", html)
        self.assertIn("&lt;b&gt;日本語教室&lt;/b&gt;", html)  # AIの文はエスケープする
        self.assertIn("営業の切り口: 教材として提案", html)
        self.assertIn("AI関連度 高", html)
        self.assertIn("2件（AI無関係判定 1件は非表示）", html)

    def test_no_toggle_when_nothing_irrelevant(self):
        html = render_site(make_config(), [make_stored_item(1)])
        self.assertNotIn('id="show-irrelevant"', html)
        self.assertNotIn('class="ai-summary"', html)


if __name__ == "__main__":
    unittest.main()
