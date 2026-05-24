import unittest

import bot


class BotHelperTest(unittest.TestCase):
    def test_require_stock_pool_ticker_accepts_known_otc_without_suffix(self):
        self.assertEqual(bot.require_stock_pool_ticker("6274"), "6274.TWO")

    def test_require_stock_pool_ticker_rejects_unknown_ticker(self):
        with self.assertRaises(ValueError):
            bot.require_stock_pool_ticker("6770")

    def test_strategy_summary_only_lists_stock_names(self):
        detailed = {
            "title": "今日策略",
            "description": "摘要",
            "color": 123,
            "fields": [
                {"name": "賣出", "value": "**聯電**（2303）｜526股｜原因"},
                {"name": "買進", "value": "**群創**（3481）｜1324股\n**大立光**（3008）｜14股"},
            ],
        }

        summary = bot.build_strategy_summary_embed(detailed)

        self.assertEqual(summary["fields"][0]["value"], "聯電")
        self.assertEqual(summary["fields"][1]["value"], "群創、大立光")


if __name__ == "__main__":
    unittest.main()
