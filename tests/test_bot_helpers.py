import unittest
import tempfile

import account_store
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

    def test_sync_buy_and_sell_append_trade_records(self):
        old_accounts_dir = account_store.ACCOUNTS_DIR
        try:
            with tempfile.TemporaryDirectory() as tmp:
                account_store.ACCOUNTS_DIR = tmp
                account_id = "tester"

                bot.sync_buy(account_id, "2303", 70.0, 100)
                account = account_store.load_account(account_id)
                self.assertEqual(len(account["trades"]), 1)
                self.assertEqual(account["trades"][0]["Side"], "BUY")
                self.assertEqual(account["trades"][0]["Ticker"], "2303.TW")

                bot.sync_sell(account_id, "2303", 80.0, 50)
                account = account_store.load_account(account_id)
                self.assertEqual(len(account["trades"]), 2)
                self.assertEqual(account["trades"][1]["Side"], "SELL")
                self.assertIn("Pnl", account["trades"][1])

                history = bot.trade_history_summary(account)
                self.assertIn("買進", history)
                self.assertIn("賣出", history)
        finally:
            account_store.ACCOUNTS_DIR = old_accounts_dir


if __name__ == "__main__":
    unittest.main()
