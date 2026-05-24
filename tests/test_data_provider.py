import unittest
from unittest.mock import patch

try:
    import pandas as pd

    import data_provider
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"optional data dependency is not installed: {exc.name}")


def sample_ohlc(open_price=10.0, close_price=11.0):
    idx = pd.to_datetime(["2026-05-20", "2026-05-21"])
    return pd.DataFrame(
        {
            "open": [open_price, open_price + 1],
            "close": [close_price, close_price + 1],
        },
        index=idx,
    )


class DataProviderTest(unittest.TestCase):
    def test_ticker_to_stock_id_removes_taiwan_suffix(self):
        self.assertEqual(data_provider.ticker_to_stock_id("2303.TW"), "2303")
        self.assertEqual(data_provider.ticker_to_stock_id("6274.TWO"), "6274")

    @patch("data_provider.fetch_yfinance_ohlc")
    @patch("data_provider.fetch_finmind_ohlc")
    def test_download_ohlc_prices_uses_finmind_first(self, finmind_mock, yfinance_mock):
        finmind_mock.return_value = sample_ohlc()

        open_df, close_df = data_provider.download_ohlc_prices(["2303.TW"], period="4mo")

        finmind_mock.assert_called_once()
        yfinance_mock.assert_not_called()
        self.assertIn("2303.TW", open_df.columns)
        self.assertIn("2303.TW", close_df.columns)

    @patch("data_provider.fetch_yfinance_ohlc")
    @patch("data_provider.fetch_finmind_ohlc")
    def test_download_ohlc_prices_falls_back_to_yfinance(self, finmind_mock, yfinance_mock):
        finmind_mock.side_effect = ValueError("FinMind failed")
        idx = pd.to_datetime(["2026-05-20", "2026-05-21"])
        yfinance_mock.return_value = (
            pd.DataFrame({"2303.TW": [10.0, 11.0]}, index=idx),
            pd.DataFrame({"2303.TW": [12.0, 13.0]}, index=idx),
        )

        open_df, close_df = data_provider.download_ohlc_prices(["2303.TW"], period="4mo")

        finmind_mock.assert_called_once()
        yfinance_mock.assert_called_once()
        self.assertEqual(float(open_df["2303.TW"].iloc[-1]), 11.0)
        self.assertEqual(float(close_df["2303.TW"].iloc[-1]), 13.0)


if __name__ == "__main__":
    unittest.main()
