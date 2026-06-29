import unittest

from nihongo_funding_watch.summarize import (
    is_boilerplate_chunk,
    relevant_snippets,
    summarize_detail,
)


class SummarizeTest(unittest.TestCase):
    def test_summarize_detail_prefixes_source_and_picks_relevant_text(self):
        text = (
            "メニュー 検索 本文へ。"
            "本事業は日本語教育の補助金を公募します。提出期限は2026年7月31日です。"
            "このサイトではJavaScriptを使用しております。"
        )
        summary = summarize_detail(text, source_url="https://example.com/x")

        self.assertTrue(summary.startswith("Source page: https://example.com/x"))
        self.assertIn("補助金", summary)
        self.assertNotIn("JavaScript", summary)

    def test_is_boilerplate_chunk(self):
        self.assertTrue(is_boilerplate_chunk("当サイトではJavaScriptを使用しております"))
        self.assertFalse(is_boilerplate_chunk("日本語教育の補助金を公募します"))

    def test_relevant_snippets_skips_short_and_boilerplate(self):
        text = "短い。日本語教育の補助金を公募する委託事業の募集を開始しました。MENU 検索"
        snippets = relevant_snippets(text)
        self.assertTrue(any("補助金" in snippet for snippet in snippets))
        self.assertFalse(any("MENU" in snippet for snippet in snippets))


if __name__ == "__main__":
    unittest.main()
