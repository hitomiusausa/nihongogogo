import unittest
from datetime import date

from nihongo_funding_watch.deadlines import extract_deadline


class DeadlineTest(unittest.TestCase):
    def test_extracts_japanese_deadline(self):
        text = "応募締切は2026年7月15日午後5時までです。"
        self.assertEqual(
            extract_deadline(text, today=date(2026, 6, 29)),
            date(2026, 7, 15),
        )

    def test_extracts_reiwa_deadline(self):
        text = "提出期限：令和8年8月3日（月）必着"
        self.assertEqual(
            extract_deadline(text, today=date(2026, 6, 29)),
            date(2026, 8, 3),
        )

    def test_extracts_month_day_as_next_future_date(self):
        text = "募集期間は7月5日まで。"
        self.assertEqual(
            extract_deadline(text, today=date(2026, 6, 29)),
            date(2026, 7, 5),
        )

    def test_month_day_uses_nearby_era_year(self):
        text = "説明会：令和8年5月26日。事前申込：5月25日17時まで。"
        self.assertEqual(
            extract_deadline(text, today=date(2026, 6, 29)),
            date(2026, 5, 25),
        )


if __name__ == "__main__":
    unittest.main()
