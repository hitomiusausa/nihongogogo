import unittest

from nihongo_funding_watch.site import linkify_html, safe_url, split_amount, truncate


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


if __name__ == "__main__":
    unittest.main()
