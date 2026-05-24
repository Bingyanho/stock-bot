"""
backtest.py — 量化策略回測引擎（統一版）
策略邏輯與 trend_trader.py 完全同步
"""
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from dataclasses import dataclass, field

from config import (
    BENCHMARK,
    COOLDOWN_DAYS,
    END_DATE,
    EXIT_BUFFER,
    INITIAL_CAPITAL,
    MAX_POSITIONS,
    MIN_HOLD_DAYS,
    MIN_MOMENTUM_THRESHOLD,
    MOMENTUM_DAYS,
    POSITION_SIZE,
    SCAN_UNIVERSE,
    SLIPPAGE,
    START_DATE,
    STOP_LOSS_BUFFER,
    TARGET_WATCHLIST_SIZE,
    TRAILING_STOP_BUFFER,
    calc_fee,
    calc_tax,
    get_name,
)


# =========================================================
# 2. 資料結構
# =========================================================
@dataclass
class Position:
    ticker:      str
    name:        str
    shares:      int
    entry_price: float
    entry_idx:   int
    entry_date:  pd.Timestamp
    entry_cost:  float          # 含買進手續費的總成本
    peak_price:  float = field(init=False)

    def __post_init__(self):
        self.peak_price = self.entry_price


@dataclass
class Trade:
    date:   pd.Timestamp
    ticker: str
    name:   str
    side:   str     # BUY / SELL
    shares: int
    price:  float
    fee:    float
    tax:    float
    pnl:    float   # 0 for BUY
    pnl_pct: float  # 0 for BUY
    reason: str


# =========================================================
# 3. 工具函式
# =========================================================
def safe_price(df: pd.DataFrame, date, ticker: str) -> float:
    if ticker not in df.columns:
        return np.nan
    try:
        val = df.at[date, ticker]
        return float(val) if pd.notna(val) else np.nan
    except Exception:
        return np.nan

def max_drawdown(equity: pd.Series):
    peak = equity.cummax()
    dd   = equity / peak - 1.0
    return float(dd.min()), dd

def performance_metrics(equity: pd.Series) -> dict:
    daily_ret    = equity.pct_change().dropna()
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0
    days         = (equity.index[-1] - equity.index[0]).days
    years        = days / 365.25 if days > 0 else np.nan
    cagr         = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years and years > 0 else np.nan
    vol          = daily_ret.std() * np.sqrt(252) if len(daily_ret) > 1 else np.nan
    sharpe       = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if (len(daily_ret) > 1 and daily_ret.std() > 0) else np.nan
    mdd, dd_s    = max_drawdown(equity)
    return {
        "total_return":    total_return,
        "cagr":            cagr,
        "volatility":      vol,
        "sharpe":          sharpe,
        "max_drawdown":    mdd,
        "drawdown_series": dd_s,
    }


# =========================================================
# 4. 資料下載 & 指標計算
# =========================================================
def download_data(tickers, start=START_DATE, end=END_DATE):
    print(f"下載 {len(tickers)} 檔資料中 ({start} ~ {end or '今天'})...")
    raw = yf.download(
        tickers=tickers, start=start, end=end,
        auto_adjust=True, progress=False, group_by="column"
    )
    if raw.empty:
        raise ValueError("無法取得資料，請檢查代號或網路。")

    open_df  = raw["Open"].copy()
    close_df = raw["Close"].copy()

    if isinstance(open_df, pd.Series):
        open_df  = open_df.to_frame()
        close_df = close_df.to_frame()

    idx      = open_df.index.intersection(close_df.index)
    open_df  = open_df.loc[idx].ffill()
    close_df = close_df.loc[idx].ffill()
    return open_df, close_df


def compute_indicators(close_df: pd.DataFrame):
    ma5   = close_df.rolling(5).mean()
    ma20  = close_df.rolling(20).mean()
    ma60  = close_df.rolling(60).mean()
    ma200 = close_df.rolling(200).mean()
    mom   = close_df.pct_change(MOMENTUM_DAYS)
    return ma5, ma20, ma60, ma200, mom


# =========================================================
# 5. 回測主體
# =========================================================
def backtest_strategy(open_df, close_df, ma5, ma20, ma60, ma200, momentum):
    available = [t for t in SCAN_UNIVERSE if t in close_df.columns]

    start_idx = 200          # 等年線就緒
    end_idx   = len(close_df) - 2  # 留一天做隔日開盤成交

    cash       = INITIAL_CAPITAL
    positions  = {}   # ticker -> Position
    cooldowns  = {}   # ticker -> 可再買進的 idx（不含）
    trades     = []
    equity_curve = []

    for i in range(start_idx, end_idx + 1):
        signal_date = close_df.index[i]
        exec_date   = close_df.index[i + 1]

        # 清除過期冷卻
        cooldowns = {t: until for t, until in cooldowns.items() if until > i}

        # ── 大盤濾網 ────────────────────────────────────
        bench_c   = safe_price(close_df, signal_date, BENCHMARK)
        bench_m200 = float(ma200[BENCHMARK].iloc[i]) if BENCHMARK in ma200.columns else np.nan
        market_ok = pd.notna(bench_c) and pd.notna(bench_m200) and bench_c > bench_m200

        # ── 產生候選股 ────────────────────────────────────
        candidates = []
        for t in available:
            px  = float(close_df[t].iloc[i])
            m20 = float(ma20[t].iloc[i])
            m60 = float(ma60[t].iloc[i])
            mom = float(momentum[t].iloc[i])
            if any(np.isnan(v) for v in [px, m20, m60, mom]):
                continue
            if px > m20 and m20 > m60 and mom > MIN_MOMENTUM_THRESHOLD:
                candidates.append((t, mom))
        candidates.sort(key=lambda x: x[1], reverse=True)
        watchlist_today = [t for t, _ in candidates[:TARGET_WATCHLIST_SIZE]]

        # ── 賣出邏輯（signal_date 觸發，exec_date 開盤成交）────
        sell_reasons = {}
        for ticker, pos in list(positions.items()):
            if ticker not in close_df.columns:
                continue
            cur_close = float(close_df[ticker].iloc[i])
            cur_m5    = float(ma5[ticker].iloc[i])  if ticker in ma5.columns  else np.nan
            cur_m20   = float(ma20[ticker].iloc[i]) if ticker in ma20.columns else np.nan
            if any(np.isnan(v) for v in [cur_close, cur_m20]):
                continue

            # 更新高點
            pos.peak_price = max(pos.peak_price, cur_close)

            held_days = i - pos.entry_idx

            # 保命條款（無視持有天數）
            market_exit    = (not market_ok) and (cur_close < cur_m20)
            hard_stop      = cur_close < pos.entry_price * STOP_LOSS_BUFFER
            trailing_stop  = cur_close < pos.peak_price * TRAILING_STOP_BUFFER

            # 趨勢條款（需滿足最短持有天數）
            trend_exit     = (cur_close < cur_m20 * EXIT_BUFFER) and (held_days >= MIN_HOLD_DAYS)
            momentum_decay = (not np.isnan(cur_m5)) and \
                             (cur_close < cur_m5) and \
                             (cur_close < pos.entry_price * 1.05) and \
                             (held_days >= MIN_HOLD_DAYS)

            if market_exit:
                sell_reasons[ticker] = "大盤轉空"
            elif hard_stop:
                sell_reasons[ticker] = "硬性停損"
            elif trailing_stop:
                sell_reasons[ticker] = "移動停利"
            elif trend_exit:
                sell_reasons[ticker] = "趨勢破壞"
            elif momentum_decay:
                sell_reasons[ticker] = "動能衰退"

        # 用隔天開盤成交
        for ticker, reason in sell_reasons.items():
            pos = positions[ticker]
            sp = safe_price(open_df, exec_date, ticker)
            if np.isnan(sp): sp = safe_price(close_df, exec_date, ticker)
            if np.isnan(sp): continue

            sell_price = sp * (1 - SLIPPAGE)
            gross      = pos.shares * sell_price
            fee        = calc_fee(gross)
            tax        = calc_tax(gross)
            net        = gross - fee - tax
            pnl        = net - pos.entry_cost
            pnl_pct    = (pnl / pos.entry_cost * 100) if pos.entry_cost > 0 else 0

            cash += net
            cooldowns[ticker] = i + COOLDOWN_DAYS
            trades.append(Trade(
                date=exec_date, ticker=ticker, name=pos.name,
                side="SELL", shares=pos.shares, price=sell_price,
                fee=fee, tax=tax, pnl=pnl, pnl_pct=pnl_pct, reason=reason
            ))
            del positions[ticker]

        # ── 買進邏輯（signal_date 觸發，exec_date 開盤成交）────
        if market_ok and len(positions) < MAX_POSITIONS:
            held_set = set(positions.keys())
            open_val = sum(
                float(open_df[t].iloc[i + 1]) * positions[t].shares
                for t in positions if t in open_df.columns
                if not np.isnan(open_df[t].iloc[i + 1])
            )
            total_equity   = cash + open_val
            budget_per_pos = total_equity * POSITION_SIZE

            for ticker, _ in candidates:
                if len(positions) >= MAX_POSITIONS:
                    break
                if ticker in held_set or ticker in cooldowns:
                    continue
                if ticker not in watchlist_today:
                    continue

                bp = safe_price(open_df, exec_date, ticker)
                if np.isnan(bp): bp = safe_price(close_df, exec_date, ticker)
                if np.isnan(bp) or bp <= 0: continue

                buy_price = bp * (1 + SLIPPAGE)
                shares    = int(budget_per_pos // buy_price)
                if shares < 1: continue

                gross      = shares * buy_price
                fee        = calc_fee(gross)
                total_cost = gross + fee
                if cash < total_cost: continue

                cash -= total_cost
                positions[ticker] = Position(
                    ticker=ticker, name=get_name(ticker),
                    shares=shares, entry_price=buy_price,
                    entry_idx=i + 1, entry_date=exec_date,
                    entry_cost=total_cost,
                )
                held_set.add(ticker)
                trades.append(Trade(
                    date=exec_date, ticker=ticker, name=get_name(ticker),
                    side="BUY", shares=shares, price=buy_price,
                    fee=fee, tax=0.0, pnl=0.0, pnl_pct=0.0,
                    reason="趨勢+動能買進"
                ))

        # ── 每日資產估值 ────────────────────────────────────
        stock_val = sum(
            float(close_df[t].iloc[i + 1]) * pos.shares
            for t, pos in positions.items()
            if t in close_df.columns and not np.isnan(close_df[t].iloc[i + 1])
        )
        equity_curve.append((exec_date, cash + stock_val))

    equity = pd.Series(
        [x[1] for x in equity_curve],
        index=pd.to_datetime([x[0] for x in equity_curve]),
        name="Strategy",
    )
    trades_df = pd.DataFrame([t.__dict__ for t in trades])
    return equity, trades_df


# =========================================================
# 6. 0050 對照組（起算點與策略一致）
# =========================================================
def backtest_benchmark(open_df, close_df, strategy_start_idx=201):
    if BENCHMARK not in close_df.columns:
        raise ValueError(f"找不到 {BENCHMARK}")

    exec_date  = close_df.index[strategy_start_idx]
    bp         = safe_price(open_df, exec_date, BENCHMARK)
    if np.isnan(bp): bp = safe_price(close_df, exec_date, BENCHMARK)

    buy_price  = bp * (1 + SLIPPAGE)
    fee        = calc_fee(INITIAL_CAPITAL)
    shares     = int((INITIAL_CAPITAL - fee) // buy_price)
    if shares < 1: raise ValueError("0050 資金不足")

    bench_cash = INITIAL_CAPITAL - shares * buy_price - fee

    bench_curve = []
    for dt in close_df.index[strategy_start_idx:]:
        px = safe_price(close_df, dt, BENCHMARK)
        if np.isnan(px): continue
        bench_curve.append((dt, bench_cash + shares * px))

    bench = pd.Series(
        [x[1] for x in bench_curve],
        index=pd.to_datetime([x[0] for x in bench_curve]),
        name="0050",
    )
    return bench


# =========================================================
# 7. 績效報告
# =========================================================
def print_report(strategy_eq, benchmark_eq, trades_df):
    idx     = strategy_eq.index.intersection(benchmark_eq.index)
    s_eq    = strategy_eq.loc[idx]
    b_eq    = benchmark_eq.loc[idx]
    sm      = performance_metrics(s_eq)
    bm      = performance_metrics(b_eq)

    sell_df = trades_df[trades_df["side"] == "SELL"] if not trades_df.empty else pd.DataFrame()
    win_rate  = (sell_df["pnl"] > 0).mean() * 100 if len(sell_df) > 0 else np.nan
    avg_pnl   = sell_df["pnl"].mean() if len(sell_df) > 0 else np.nan
    total_fee = trades_df["fee"].sum() if not trades_df.empty else 0
    total_tax = trades_df["tax"].sum() if not trades_df.empty else 0

    print("\n" + "="*60)
    print(f"{'指標':<20} {'策略':>12} {'0050':>12}")
    print("="*60)
    rows = [
        ("期末資產",       f"{s_eq.iloc[-1]:>12,.0f}", f"{b_eq.iloc[-1]:>12,.0f}"),
        ("總報酬率",       f"{sm['total_return']*100:>11.2f}%", f"{bm['total_return']*100:>11.2f}%"),
        ("年化報酬率(CAGR)",f"{sm['cagr']*100:>11.2f}%", f"{bm['cagr']*100:>11.2f}%"),
        ("年化波動率",     f"{sm['volatility']*100:>11.2f}%", f"{bm['volatility']*100:>11.2f}%"),
        ("Sharpe Ratio",  f"{sm['sharpe']:>12.2f}", f"{bm['sharpe']:>12.2f}"),
        ("最大回撤",       f"{sm['max_drawdown']*100:>11.2f}%", f"{bm['max_drawdown']*100:>11.2f}%"),
    ]
    for name, sv, bv in rows:
        print(f"{name:<20} {sv} {bv}")
    print("="*60)
    print(f"\n交易統計：買進 {(trades_df['side']=='BUY').sum()} 次 | 賣出 {len(sell_df)} 次")
    if not np.isnan(win_rate): print(f"勝率：{win_rate:.1f}%  平均單筆損益：{avg_pnl:,.0f} 元")
    print(f"總手續費：{total_fee:,.0f} 元  總稅金：{total_tax:,.0f} 元")


def plot_results(strategy_eq, benchmark_eq):
    idx = strategy_eq.index.intersection(benchmark_eq.index)
    s   = strategy_eq.loc[idx] / strategy_eq.loc[idx].iloc[0]
    b   = benchmark_eq.loc[idx] / benchmark_eq.loc[idx].iloc[0]

    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})

    axes[0].plot(s.index, s.values, label="策略", linewidth=1.5)
    axes[0].plot(b.index, b.values, label="0050", linewidth=1.5, alpha=0.8)
    axes[0].set_title("策略 vs 0050 (標準化淨值)", fontsize=13)
    axes[0].set_ylabel("淨值 (倍)")
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    _, s_dd = max_drawdown(strategy_eq.loc[idx])
    _, b_dd = max_drawdown(benchmark_eq.loc[idx])
    axes[1].fill_between(s_dd.index, s_dd.values, 0, alpha=0.4, label="策略 DD")
    axes[1].fill_between(b_dd.index, b_dd.values, 0, alpha=0.3, label="0050 DD")
    axes[1].set_title("回撤比較", fontsize=11)
    axes[1].set_ylabel("Drawdown")
    axes[1].legend()
    axes[1].grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig("backtest_result.png", dpi=150)
    plt.show()
    print("圖表已儲存：backtest_result.png")


# =========================================================
# 8. 主程式
# =========================================================
def main():
    tickers        = list(dict.fromkeys(SCAN_UNIVERSE + [BENCHMARK]))
    open_df, close_df = download_data(tickers)

    ma5, ma20, ma60, ma200, momentum = compute_indicators(close_df)

    # 策略回測
    strategy_eq, trades_df = backtest_strategy(open_df, close_df, ma5, ma20, ma60, ma200, momentum)

    # 0050 對照（起算點 index[201] = 策略的第一個 exec_date）
    benchmark_eq = backtest_benchmark(open_df, close_df, strategy_start_idx=201)

    # 報告
    print_report(strategy_eq, benchmark_eq, trades_df)

    # 輸出
    if not trades_df.empty:
        trades_df.to_csv("trade_log.csv", index=False, encoding="utf-8-sig")
        print("\n交易明細已輸出：trade_log.csv")

    eq_df = pd.DataFrame({"Strategy": strategy_eq, "0050": benchmark_eq})
    eq_df.to_csv("equity_curve.csv", encoding="utf-8-sig")
    print("權益曲線已輸出：equity_curve.csv")

    plot_results(strategy_eq, benchmark_eq)


if __name__ == "__main__":
    main()
