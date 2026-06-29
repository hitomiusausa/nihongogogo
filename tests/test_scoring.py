import unittest

from nihongo_funding_watch.config import PageSource, WatchConfig
from nihongo_funding_watch.fetchers import FetchedItem
from nihongo_funding_watch.scoring import score_item


class ScoringTest(unittest.TestCase):
    def test_scores_funding_and_japanese_education_terms(self):
        config = WatchConfig(
            minimum_score=3,
            google_news_queries=[],
            google_news_sources=[],
            page_sources=[PageSource(name="x", url="https://example.com", allow_url_patterns=[])],
            exclude_urls=[],
            exclude_title_patterns=[],
            generic_link_title_patterns=[],
            categories={
                "公募・補助金・プロポーザル": ["公募", "補助金"],
                "ニュース（日本語教育）": ["日本語教育"],
            },
            keyword_weights={"公募": 4, "補助金": 5, "日本語教育": 4},
            sales_angles={},
        )
        item = FetchedItem(
            title="自治体が日本語教育の補助金事業を公募",
            url="https://example.com/a",
            source_name="test",
            source_type="test",
        )

        scored = score_item(config, item)

        self.assertEqual(scored.score, 13)
        self.assertEqual(scored.primary_category, "公募・補助金・プロポーザル")
        self.assertIn("日本語教育", scored.matched_keywords)


if __name__ == "__main__":
    unittest.main()
