from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from config import FINMIND_TOKEN

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
FINMIND_DATASETS = ("TaiwanStockPriceAdj", "TaiwanStockPrice")

try:
    yf.set_tz_cache_location(str(Path("/tmp/py-yfinance-cache")))
except Exception:
    pass


def ticker_to_stock_id(ticker: str) -> str:
    return ticker.replace(".TW", "").replace(".TWO", "")


def resolve_dates(period: str | None = None, start: str | None = None, end: str | None = None):
    end_date = pd.Timestamp(end or datetime.today().date())
    if start:
        start_date = pd.Timestamp(start)
    elif period == "4mo":
        start_date = end_date - pd.Timedelta(days=150)
    elif period == "2y":
        start_date = end_date - pd.Timedelta(days=760)
    else:
        start_date = end_date - pd.Timedelta(days=760)
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def fetch_finmind_dataset(ticker: str, dataset: str, start: str, end: str) -> pd.DataFrame:
    params = {
        "dataset": dataset,
        "data_id": ticker_to_stock_id(ticker),
        "start_date": start,
        "end_date": end,
    }
    headers = {}
    if FINMIND_TOKEN:
        params["token"] = FINMIND_TOKEN
        headers["Authorization"] = f"Bearer {FINMIND_TOKEN}"

    response = requests.get(FINMIND_URL, params=params, headers=headers, timeout=20)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", [])
    if not data:
        msg = payload.get("msg") or "no data"
        raise ValueError(f"FinMind {dataset} 無法取得 {ticker} 資料：{msg}")

    df = pd.DataFrame(data)
    if "date" not in df or "open" not in df or "close" not in df:
        raise ValueError(f"FinMind {dataset} {ticker} 回傳欄位缺少 date/open/close")

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df[["open", "close"]].astype(float)


def fetch_finmind_ohlc(ticker: str, start: str, end: str) -> pd.DataFrame:
    last_error = None
    for dataset in FINMIND_DATASETS:
        try:
            return fetch_finmind_dataset(ticker, dataset, start, end)
        except Exception as exc:
            last_error = exc
    raise ValueError(f"FinMind 無法取得 {ticker} 資料：{last_error}")


def fetch_yfinance_ohlc(tickers: list[str], start: str, end: str):
    if not tickers:
        return pd.DataFrame(), pd.DataFrame()

    raw = yf.download(
        tickers=tickers,
        start=start,
        end=(pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
        group_by="column",
    )
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame()

    open_df = raw["Open"].copy()
    close_df = raw["Close"].copy()
    if isinstance(open_df, pd.Series):
        open_df = open_df.to_frame(name=tickers[0])
        close_df = close_df.to_frame(name=tickers[0])

    return open_df, close_df


def download_ohlc_prices(tickers, period: str | None = None, start: str | None = None, end: str | None = None):
    tickers = list(dict.fromkeys(tickers))
    start_date, end_date = resolve_dates(period=period, start=start, end=end)

    open_parts = {}
    close_parts = {}
    fallback_tickers = []

    for ticker in tickers:
        try:
            df = fetch_finmind_ohlc(ticker, start_date, end_date)
            open_parts[ticker] = df["open"]
            close_parts[ticker] = df["close"]
        except Exception:
            fallback_tickers.append(ticker)

    if fallback_tickers:
        yf_open, yf_close = fetch_yfinance_ohlc(fallback_tickers, start_date, end_date)
        for ticker in fallback_tickers:
            if ticker in yf_open.columns and ticker in yf_close.columns:
                open_parts[ticker] = yf_open[ticker].dropna()
                close_parts[ticker] = yf_close[ticker].dropna()

    if not close_parts:
        raise RuntimeError("FinMind 與 yfinance 都無法取得市場資料")

    open_df = pd.DataFrame(open_parts).sort_index().ffill().dropna(how="all")
    close_df = pd.DataFrame(close_parts).sort_index().ffill().dropna(how="all")
    idx = open_df.index.intersection(close_df.index)
    return open_df.loc[idx], close_df.loc[idx]


def download_close_prices(tickers, period: str | None = None, start: str | None = None, end: str | None = None):
    _, close_df = download_ohlc_prices(tickers, period=period, start=start, end=end)
    return close_df
