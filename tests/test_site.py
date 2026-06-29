import unittest

from nihongo_funding_watch.site import linkify_html, safe_url, truncate


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


if __name__ == "__main__":
    unittest.main()
