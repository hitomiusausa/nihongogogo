import unittest

from nihongo_funding_watch.config import PageSource
from nihongo_funding_watch.fetchers import (
    is_duplicate_title_key,
    parse_kp2mi_gtog_japan,
    parse_dolab_static,
    parse_japanese_date,
    parse_mext_boshu,
    parse_municipality_focus,
    title_fingerprint,
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

    def test_parse_kp2mi_gtog_japan_reads_api_rows_with_country_summary(self):
        source = PageSource(
            name="インドネシア KP2MI/BP2MI G to G Japan",
            url="https://kp2mi.go.id/gtog-data/jepang/Pengumuman?draw=1&start=0&length=20",
            allow_url_patterns=[],
            parser="kp2mi_gtog_japan",
            country="インドネシア",
        )
        body = b"""
        {
          "data": [{
            "judul": "<a href=\\"/gtog-detail/jepang/sample\\">PENGUMUMAN UJIAN BAHASA JEPANG DASAR PROGRAM G TO G JEPANG</a>",
            "gtgjepang": "<p>Calon PMI kandidat nurse dan careworker mengikuti ujian bahasa Jepang.</p>",
            "tanggal": "22 June 2026",
            "slug": "sample"
          }]
        }
        """

        items = parse_kp2mi_gtog_japan(body, source)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].country, "インドネシア")
        self.assertEqual(items[0].published_at.isoformat(), "2026-06-22T00:00:00+00:00")
        self.assertIn("日本語概要", items[0].summary)
        self.assertIn("G to G 日本派遣", items[0].summary)

    def test_parse_dolab_static_uses_content_heading_not_header_logo(self):
        source = PageSource(
            name="ベトナム DOLAB-JICA 特定技能情報",
            url="https://vieclamngoainuoc.dolab.gov.vn/loai-hinh/SSW",
            allow_url_patterns=[],
            parser="dolab_static",
            country="ベトナム",
        )
        body = """
        <html><head><title>DOLAB-JICA-Lao động kỹ năng đặc định</title></head>
        <body>
        <header><h3>DOLAB-JICA</h3><script>window.dataLayer = [];</script></header>
        <section>
          <h3>THÔNG TIN CHO NGƯỜI LAO ĐỘNG ĐI LÀM VIỆC TẠI THỊ TRƯỜNG NHẬT BẢN</h3>
          <p>Chương trình lao động kỹ năng đặc định, thực tập kỹ năng, điều dưỡng hộ lý.</p>
          <p>Có chứng chỉ tiếng Nhật N4 JLPT hoặc JFT Basic.</p>
        </section>
        </body></html>
        """.encode()

        items = parse_dolab_static(body, source)

        self.assertEqual(items[0].title, "THÔNG TIN CHO NGƯỜI LAO ĐỘNG ĐI LÀM VIỆC TẠI THỊ TRƯỜNG NHẬT BẢN")
        self.assertEqual(items[0].country, "ベトナム")
        self.assertIn("JFT-Basic/JLPT", items[0].summary)
        self.assertNotIn("window.dataLayer", items[0].summary)


class ParseRssPublisherTest(unittest.TestCase):
    def test_google_news_summary_shows_publisher_instead_of_title_echo(self):
        body = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
        <item>
          <title>外国人材の日本語教育に補助 香川県 - 四国新聞</title>
          <link>https://news.google.com/rss/articles/abc?oc=5</link>
          <pubDate>Wed, 16 Jul 2026 00:00:00 GMT</pubDate>
          <description>&lt;a href="https://news.google.com/rss/articles/abc?oc=5"&gt;外国人材の日本語教育に補助 香川県&lt;/a&gt;&amp;nbsp;&amp;nbsp;四国新聞</description>
        </item>
        </channel></rss>""".encode("utf-8")

        from nihongo_funding_watch.fetchers import parse_rss

        items = parse_rss(body, source_name="Google News: q", source_type="google_news")

        self.assertEqual(items[0].title, "外国人材の日本語教育に補助 香川県")
        self.assertEqual(items[0].summary, "掲載元: 四国新聞")

    def test_google_news_summary_empty_when_no_publisher_suffix(self):
        body = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
        <item>
          <title>タイトルのみの記事</title>
          <link>https://news.google.com/rss/articles/xyz?oc=5</link>
        </item>
        </channel></rss>""".encode("utf-8")

        from nihongo_funding_watch.fetchers import parse_rss

        items = parse_rss(body, source_name="Google News: q", source_type="google_news")

        self.assertEqual(items[0].summary, "")


class TitleFingerprintTest(unittest.TestCase):
    def test_wave_dash_variants_share_fingerprint(self):
        # 実データ: 同一プレスリリースが ～/〜/なし の3表記で4カード表示された
        base = title_fingerprint(
            "文部科学省委託「子どものための日本語教育研修」応募受付開始 外国人児童生徒支援に携わる日本語教師を育成"
        )
        self.assertEqual(
            title_fingerprint(
                "文部科学省委託「子どものための日本語教育研修」応募受付開始 〜外国人児童生徒支援に携わる日本語教師を育成〜"
            ),
            base,
        )
        self.assertEqual(
            title_fingerprint(
                "文部科学省委託「子どものための日本語教育研修」応募受付開始 ～外国人児童生徒支援に携わる日本語教師を育成～"
            ),
            base,
        )

    def test_fullwidth_bracket_and_media_suffix_share_fingerprint(self):
        # 実データ: ［川崎区役所主催］…（PR TIMES） と 【川崎区役所主催】… が2カード表示された
        self.assertEqual(
            title_fingerprint(
                "［川崎区役所主催］就労分野の認定日本語教育機関による実証事業「就労者のための日本語講座」を実施します（PR TIMES）"
            ),
            title_fingerprint(
                "【川崎区役所主催】就労分野の認定日本語教育機関による実証事業「就労者のための日本語講座」を実施します"
            ),
        )


class DuplicateTitleKeyTest(unittest.TestCase):
    def _key(self, title: str) -> str:
        return title_fingerprint(title)

    def test_truncated_prefix_is_duplicate(self):
        full = self._key(
            "文部科学省委託「子どものための日本語教育研修」応募受付開始 ～外国人児童生徒支援に携わる日本語教師を育成～"
        )
        truncated = self._key(
            "文部科学省委託「子どものための日本語教育研修」応募受付開始 ～外国人児童生徒..（認定NPO法人メタノイア プレスリリース）"
        )
        self.assertTrue(is_duplicate_title_key(full, truncated))

    def test_company_prefix_variants_are_duplicates(self):
        left = self._key(
            "明光ネットワークジャパンの子会社、明光キャリアパートナーズ 令和8年度広島県「外国人材日本語学習支援業務」を受託"
        )
        right = self._key(
            "株式会社明光キャリアパートナーズ 令和8年度広島県「外国人材日本語学習支援業務」を受託"
        )
        self.assertTrue(is_duplicate_title_key(left, right))

    def test_different_announcements_with_shared_boilerplate_are_not_duplicates(self):
        # 実データ: KP2MIの別告示同士は長い定型句を共有するが別物
        left = self._key(
            "PENGUMUMAN HASIL PEMERIKSAAN PSIKOLOGI, PEMANGGILAN KANDIDAT WAITING LIST, DAN PELAKSANAAN MEDICAL CHECK UP I CALON KANDIDAT NURSE DAN CAREWORKER PEKERJA MIGRAN INDONESIA PROGRAM G TO G JEPANG BATCH XX TAHUN PENEMPATAN 2027"
        )
        right = self._key(
            "PENGUMUMAN HASIL PEMERIKSAAN PSIKOLOGI KANDIDAT WAITING LIST DAN DAFTAR KETERLAMBATAN HASIL PEMERIKSAAN PSIKOLOGI CALON KANDIDAT NURSE DAN CAREWORKER PEKERJA MIGRAN INDONESIA PROGRAM G TO G JEPANG BATCH XX TAHUN PENEMPATAN 2027"
        )
        self.assertFalse(is_duplicate_title_key(left, right))

    def test_different_fiscal_years_are_not_duplicates(self):
        left = self._key("令和7年度外国人材受入加速化支援事業に係る受託事業者の募集について")
        right = self._key("令和8年度外国人材受入加速化支援事業に係る受託事業者の募集について")
        self.assertFalse(is_duplicate_title_key(left, right))

    def test_short_keys_never_merge_by_containment(self):
        self.assertFalse(
            is_duplicate_title_key(self._key("監理措置制度"), self._key("監理措置制度の改正が入管法に与える影響"))
        )


if __name__ == "__main__":
    unittest.main()
