import unittest

from account_store import default_account
from account_store import account_path
from config import (
    INITIAL_CAPITAL,
    MAX_POSITIONS,
    MIN_FEE,
    POSITION_SIZE,
    calc_fee,
    calc_tax,
    get_name,
)


class ConfigTests(unittest.TestCase):
    def test_position_size_matches_max_positions(self):
        self.assertAlmostEqual(POSITION_SIZE, 1.0 / MAX_POSITIONS)

    def test_transaction_cost_helpers(self):
        self.assertEqual(calc_fee(100), MIN_FEE)
        self.assertEqual(calc_tax(100000), 300)

    def test_stock_name_fallback(self):
        self.assertEqual(get_name("2330.TW"), "台積電")
        self.assertEqual(get_name("UNKNOWN"), "UNKNOWN")

    def test_default_account_shape(self):
        account = default_account()
        self.assertEqual(account["cash"], INITIAL_CAPITAL)
        self.assertEqual(account["invested_capital"], INITIAL_CAPITAL)
        self.assertEqual(account["portfolio"], [])
        self.assertEqual(account["cooldowns"], {})

    def test_user_account_path_is_sanitized(self):
        self.assertEqual(account_path("user:123"), "accounts\\user_123.json")


if __name__ == "__main__":
    unittest.main()
