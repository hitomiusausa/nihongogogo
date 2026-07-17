import unittest

from nihongo_funding_watch.site import linkify_html, render_health, safe_url, truncate


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

    def test_render_health_lists_errors_and_silent_sources(self):
        html = render_health(
            {
                "checked_at": "2026-07-17T00:00:00+00:00",
                "fetched": 2245,
                "errors": ["Page source failed: 岐阜県 多文化共生補助金: HTTP 404 ..."],
                "zero_page_sources": ["文化庁 公募情報"],
            }
        )
        self.assertIn("収集ヘルス", html)
        self.assertIn("岐阜県 多文化共生補助金", html)
        self.assertIn("取得0件: 文化庁 公募情報", html)

    def test_render_health_empty_when_missing(self):
        self.assertEqual(render_health(None), "")


if __name__ == "__main__":
    unittest.main()
