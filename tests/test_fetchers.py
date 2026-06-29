import unittest

from nihongo_funding_watch.config import PageSource
from nihongo_funding_watch.fetchers import (
    parse_japanese_date,
    parse_mext_boshu,
    parse_municipality_focus,
)


class FetchersTest(unittest.TestCase):
    def test_parse_mext_boshu_reads_listing_date_and_item(self):
        source = PageSource(
            name="文部科学省 公募情報",
            url="https://www.mext.go.jp/b_menu/boshu/index.htm",
            allow_url_patterns=[
                r"^https://www\.mext\.go\.jp/b_menu/boshu/detail/mext_[0-9]+\.html$"
            ],
            parser="mext_boshu",
        )
        body = """
        <h3 class="dashedline"><a name="information2" id="information2"></a>公募情報</h3>
        <div class="dateList">
        <dl>
        <dt>令和8年6月3日</dt>
        <dd><a href="/b_menu/boshu/detail/mext_00535.html">令和９年度マレーシア政府派遣留学生予備教育派遣教員の募集</a></dd>
        </dl>
        </div><!-- /カテゴリ別一覧（公募情報） -->
        """.encode()

        items = parse_mext_boshu(body, source)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].published_at.isoformat(), "2026-06-03T00:00:00+00:00")
        self.assertIn("派遣留学生", items[0].title)
        self.assertIn("一覧掲載日: 令和8年6月3日", items[0].summary)

    def test_parse_japanese_date_supports_era_year(self):
        parsed = parse_japanese_date("令和元年5月1日")

        self.assertEqual(parsed.isoformat(), "2019-05-01T00:00:00+00:00")

    def test_parse_municipality_focus_skips_attachments(self):
        source = PageSource(
            name="自治体テスト",
            url="https://www.pref.example.jp/page/1.html",
            allow_url_patterns=[r"^https://www\.pref\.example\.jp/.+"],
            parser="municipality_focus",
        )
        body = """
        <html><head><title>外国人介護人材日本語学習支援事業費補助金 - 県</title></head>
        <body>
        <h1>外国人介護人材日本語学習支援事業費補助金</h1>
        <a href="/uploaded/form.xlsx">外国人介護人材日本語学習支援事業費補助金申請様式</a>
        <a href="/page/detail.html">令和8年度外国人材受入支援補助金</a>
        <a href="/page/seminar.html">外国人材セミナー</a>
        </body></html>
        """.encode()

        items = parse_municipality_focus(body, source)

        self.assertEqual(
            [item.title for item in items],
            [
                "外国人介護人材日本語学習支援事業費補助金",
                "令和8年度外国人材受入支援補助金",
            ],
        )


if __name__ == "__main__":
    unittest.main()
