import unittest

from nihongo_funding_watch.amounts import extract_amount


class ExtractAmountTest(unittest.TestCase):
    def test_finds_upper_limit_amount(self):
        self.assertEqual(extract_amount("補助金の上限は100万円です"), "上限100万円")

    def test_finds_amount_with_limit_suffix(self):
        self.assertEqual(
            extract_amount("1事業者あたり50万円を上限に補助します"), "上限50万円"
        )

    def test_finds_limit_label_with_fullwidth_digits(self):
        self.assertEqual(
            extract_amount("補助限度額：３００万円（千円未満切捨て）"), "上限300万円"
        )

    def test_combines_amount_and_subsidy_rate(self):
        self.assertEqual(
            extract_amount("補助率は2分の1以内、上限額は300万円です"),
            "上限300万円・補助率2分の1",
        )

    def test_rate_only(self):
        self.assertEqual(extract_amount("補助率: 1/2（対象経費の半額）"), "補助率1／2")

    def test_normalizes_thousand_yen_unit(self):
        # 実データ: 福岡県ページの「上限5,000千円」
        self.assertEqual(extract_amount("補助上限額は5,000千円です"), "上限500万円")

    def test_normalizes_raw_yen_to_readable_units(self):
        # 実データ: 大阪府ページの「76,676,000円を上限」
        self.assertEqual(
            extract_amount("委託料 76,676,000円を上限とする"), "上限7667万6000円"
        )

    def test_normalizes_decimal_oku(self):
        self.assertEqual(extract_amount("上限1.5億円"), "上限1億5000万円")

    def test_returns_empty_when_no_amount(self):
        self.assertEqual(extract_amount("応募方法は下記のとおりです"), "")

    def test_ignores_plain_prices_without_limit_context(self):
        # 「受講料5,000円」のような文言を補助金額と誤認しない
        self.assertEqual(extract_amount("説明会の参加費は5,000円です"), "")


if __name__ == "__main__":
    unittest.main()
