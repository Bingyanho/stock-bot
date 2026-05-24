import yfinance as yf
import pandas as pd
import requests
import logging
import os
import traceback
import unicodedata
from datetime import datetime, timedelta
import warnings

from account_store import load_account, save_account
from config import (
    BENCHMARK,
    COOLDOWN_DAYS,
    DISCORD_WEBHOOK_URL,
    EXIT_BUFFER,
    INITIAL_CAPITAL,
    MAX_POSITIONS,
    MIN_BUDGET_THRESHOLD,
    MIN_HOLD_DAYS,
    MIN_MOMENTUM_THRESHOLD,
    MOMENTUM_DAYS,
    POSITION_SIZE,
    SCAN_UNIVERSE,
    STOP_LOSS_BUFFER,
    TARGET_WATCHLIST_SIZE,
    TRAILING_STOP_BUFFER,
    WATCHLIST_FILE,
    calc_fee,
    calc_tax,
    get_name,
)

warnings.filterwarnings('ignore')

# ==========================================
# 0. 日誌設定
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('trading.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==========================================
# 1. 動態名單
# ==========================================
def update_dynamic_watchlist():
    print(f"啟動全市場掃描：正在分析 {len(SCAN_UNIVERSE)} 檔潛力股...")

    raw = yf.download(SCAN_UNIVERSE, period="4mo", auto_adjust=True, progress=False)

    if raw.empty or "Close" not in raw:
        raise RuntimeError("無法取得掃描池資料，請檢查網路或 yfinance 資料源。")

    close_df = raw["Close"].ffill().dropna(how="all")

    candidates = []
    for t in SCAN_UNIVERSE:
        if t not in close_df.columns:
            continue

        c = close_df[t].dropna()
        if len(c) < 60:
            continue

        last_close = float(c.iloc[-1])
        ma20 = float(c.rolling(20).mean().iloc[-1])
        ma60 = float(c.rolling(60).mean().iloc[-1])
        momentum = float(c.pct_change(MOMENTUM_DAYS).iloc[-1])

        if pd.isna(ma20) or pd.isna(ma60) or pd.isna(momentum):
            continue

        if last_close > ma20 and ma20 > ma60 and momentum > 0:
            candidates.append({"Ticker": t, "Momentum": momentum})

    candidates.sort(key=lambda x: x["Momentum"], reverse=True)
    top_stocks = [c["Ticker"] for c in candidates[:TARGET_WATCHLIST_SIZE]]

    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        f.write(f"# 機器人自動掃描更新時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("# 選股邏輯: 收盤 > 20MA > 60MA，依 10 日動能排序前 20 名\n")
        f.write("\n".join(top_stocks))

    print(f"掃描完成！已將目前最強的 {len(top_stocks)} 檔股票更新至 {WATCHLIST_FILE}")
    return top_stocks

# ==========================================
# 2. 數據引擎與指標計算
# ==========================================
def get_market_signals(tickers):
    print("正在下載觀察名單與大盤數據...")
    all_tickers = list(dict.fromkeys(tickers + [BENCHMARK]))

    raw = yf.download(all_tickers, period="2y", auto_adjust=True, progress=False)
    if raw.empty or "Close" not in raw:
        raise RuntimeError("無法取得市場資料，請檢查網路或 yfinance 資料源。")

    close_df = raw["Close"].ffill().dropna(how="all")
    signals = {}

    market_ok = False
    market_status = "🔴 大盤資料不足，暫停交易"

    if BENCHMARK in close_df.columns:
        bench_close = close_df[BENCHMARK].dropna()
        if len(bench_close) >= 200:
            bench_ma200 = bench_close.rolling(200).mean()
            if not pd.isna(bench_ma200.iloc[-1]):
                market_ok = float(bench_close.iloc[-1]) > float(bench_ma200.iloc[-1])
                market_status = "🟢 多頭 (大盤 > 年線)" if market_ok else "🔴 空頭 (大盤 < 年線，強制空手)"
        else:
            market_status = "🔴 大盤資料不足 200 日，暫停交易"

    for t in tickers:
        if t not in close_df.columns:
            continue

        c = close_df[t].dropna()
        if len(c) < 60:
            continue

        ma5 = c.rolling(5).mean().iloc[-1]
        ma20 = c.rolling(20).mean().iloc[-1]
        ma60 = c.rolling(60).mean().iloc[-1]
        momentum = c.pct_change(MOMENTUM_DAYS).iloc[-1]

        if pd.isna(ma20) or pd.isna(ma60) or pd.isna(momentum):
            continue

        signals[t] = {
            "Close": float(c.iloc[-1]),
            "MA5": float(ma5),
            "MA20": float(ma20),
            "MA60": float(ma60),
            "Momentum": float(momentum)
        }

    return market_ok, market_status, signals


def update_portfolio_peak_prices(account, signals, account_id=None):
    """Update only Peak_Price for existing holdings; no trade state is changed here."""
    changed = 0
    for pos in account.get("portfolio", []):
        ticker = pos.get("Ticker")
        if ticker not in signals:
            continue

        entry_price = pos.get("Entry_Price", 0)
        old_peak = float(pos.get("Peak_Price", entry_price))
        new_peak = round(max(old_peak, signals[ticker]["Close"]), 2)
        if new_peak > old_peak:
            pos["Peak_Price"] = new_peak
            changed += 1

    if changed:
        save_account(account, account_id)
        logger.info(f"已更新 {changed} 檔持股 Peak_Price")
    return changed

# ==========================================
# 4. 核心交易邏輯
# ==========================================
def display_width(text):
    return sum(2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1 for ch in str(text))


def pad_cell(value, width, align="left"):
    text = str(value)
    spaces = max(0, width - display_width(text))
    if align == "right":
        return " " * spaces + text
    return text + " " * spaces


def make_table(headers, rows, right_cols=None):
    right_cols = set(right_cols or [])
    rows = [[str(cell) for cell in row] for row in rows]
    widths = [
        max(display_width(headers[i]), *(display_width(row[i]) for row in rows))
        for i in range(len(headers))
    ]
    lines = [
        "  ".join(pad_cell(header, widths[i]) for i, header in enumerate(headers)),
        "  ".join("-" * width for width in widths),
    ]
    for row in rows:
        lines.append(
            "  ".join(
                pad_cell(cell, widths[i], "right" if i in right_cols else "left")
                for i, cell in enumerate(row)
            )
        )
    return "```text\n" + "\n".join(lines) + "\n```"


def format_rows(rows):
    return "\n".join(rows)


def short_ticker(ticker):
    return ticker.replace(".TWO", "").replace(".TW", "")


def run_daily_strategy(account_id=None):
    watchlist = update_dynamic_watchlist()
    account = load_account(account_id)

    cash = account["cash"]
    portfolio = account["portfolio"]
    cooldowns = account["cooldowns"]

    today = datetime.today()
    today_str = today.strftime("%Y-%m-%d")

    # 【修正】將持股代號也加入訊號下載，確保庫存中的股票一定會被監控
    portfolio_tickers = [p["Ticker"] for p in portfolio]
    all_monitor_tickers = list(dict.fromkeys(watchlist + portfolio_tickers))
    market_ok, market_status, signals = get_market_signals(all_monitor_tickers)
    update_portfolio_peak_prices(account, signals, account_id)
    sell_rows, buy_rows = [], []

    # 策略分析只使用冷卻名單判斷，不會回寫帳戶。
    active_cooldowns = {
        t: date for t, date in cooldowns.items()
        if datetime.strptime(date, "%Y-%m-%d") + timedelta(days=COOLDOWN_DAYS) > today
    }

    # --- [階段 A] 賣出邏輯 ---
    simulated_cash = cash
    simulated_portfolio = []
    suggested_sell_tickers = set()
    for pos in portfolio:
        t = pos["Ticker"]
        if t not in signals:
            simulated_portfolio.append(pos)
            continue

        price = signals[t]["Close"]
        m5 = signals[t]["MA5"]
        m20 = signals[t]["MA20"]
        
        entry_price = pos["Entry_Price"]
        peak_price = max(pos.get("Peak_Price", entry_price), price)
        
        held_days = abs((today - datetime.strptime(pos["Entry_Date"], "%Y-%m-%d")).days)

        # 保命條款 (無視持有天數，隨時觸發)
        market_exit = (not market_ok) and (price < m20)
        hard_stop = (price < entry_price * STOP_LOSS_BUFFER)
        trailing_stop = (price < peak_price * TRAILING_STOP_BUFFER)

        # 趨勢條款 (加上 held_days >= MIN_HOLD_DAYS 的限制，給予 5 天保護)
        trend_exit = (price < m20 * EXIT_BUFFER) and (held_days >= MIN_HOLD_DAYS)
        momentum_decay = (price < m5) and (price < entry_price * 1.05) and (held_days >= MIN_HOLD_DAYS)

        if market_exit or trend_exit or hard_stop or trailing_stop or momentum_decay:
            gross_value = pos["Shares"] * price
            sell_fee = calc_fee(gross_value)
            sell_tax = calc_tax(gross_value)
            net_value = gross_value - sell_fee - sell_tax
            simulated_cash += net_value

            cost_basis = (entry_price * pos["Shares"]) + pos.get("Buy_Fee", 0)
            profit_pct = ((net_value - cost_basis) / cost_basis) * 100 if cost_basis > 0 else 0

            if market_exit:
                reason = "🔴 大盤轉空強制清倉"
            elif hard_stop:
                reason = "🛑 觸發硬性停損 (跌破買價 8%)"
            elif trailing_stop:
                reason = "📉 觸發移動停利 (高點回落 10%)"
            elif momentum_decay:
                reason = "⏳ 動能衰退 (跌破5MA且獲利未拉開)"
            else:
                reason = "⚠️ 趨勢破壞 (跌破 20MA)"

            sell_rows.append([
                f"**{get_name(t)}**（{short_ticker(t)}）｜"
                f"{pos['Shares']}股｜參考 {price:.2f}｜"
                f"報酬 {profit_pct:.1f}%｜"
                f"{reason.replace('🔴 ', '').replace('🛑 ', '').replace('📉 ', '').replace('⏳ ', '').replace('⚠️ ', '')}",
            ])

            suggested_sell_tickers.add(t)
        else:
            pos_view = dict(pos)
            pos_view["Peak_Price"] = round(peak_price, 2)
            simulated_portfolio.append(pos_view)

    # --- [階段 B] 買進邏輯 (與回測一致：用總資產 × 單位部位比例) ---
    empty_slots = MAX_POSITIONS - len(simulated_portfolio)

    if market_ok and empty_slots > 0:
        # 【修正】用總資產 × POSITION_SIZE 計算預算，與回測邏輯一致
        stock_value_for_budget = sum(
            signals[p["Ticker"]]["Close"] * p["Shares"]
            for p in simulated_portfolio if p["Ticker"] in signals
        )
        total_equity = simulated_cash + stock_value_for_budget
        budget_per_stock = total_equity * POSITION_SIZE

        # 檢查預算是否有達到最低消費門檻
        if budget_per_stock >= MIN_BUDGET_THRESHOLD:
            held_tickers = [p["Ticker"] for p in simulated_portfolio]
            candidates = []

            # 篩選符合條件的候選股
            for t, s in signals.items():
                if t in held_tickers or t in active_cooldowns or t in suggested_sell_tickers:
                    continue
                if s["Close"] > s["MA20"] and s["MA20"] > s["MA60"] and s["Momentum"] > MIN_MOMENTUM_THRESHOLD:
                    candidates.append({
                        "Ticker": t,
                        "Price": s["Close"],
                        "Momentum": s["Momentum"]
                    })

            # 依照動能排序，優先買最強的
            candidates.sort(key=lambda x: x["Momentum"], reverse=True)

            for b in candidates[:empty_slots]:
                if empty_slots <= 0:
                    break
                    
                price = b["Price"]
                # 粗估可買股數 (預留 0.2% 作為手續費緩衝)
                shares = int((budget_per_stock * 0.998) // price)
                
                # 防呆機制：如果加了手續費超過現金，就減少 1 股直到夠買
                while shares > 0:
                    gross_cost = shares * price
                    buy_fee = calc_fee(gross_cost)
                    total_cost = gross_cost + buy_fee
                    if simulated_cash >= total_cost:
                        break
                    shares -= 1

                if shares < 1:
                    continue

                # 確定購買數量後，進行現金扣款與更新持股
                gross_cost = shares * price
                buy_fee = calc_fee(gross_cost)
                total_cost = gross_cost + buy_fee

                simulated_cash -= total_cost
                empty_slots -= 1
                simulated_portfolio.append({
                    "Ticker": b["Ticker"],
                    "Name": get_name(b["Ticker"]),
                    "Shares": shares,
                    "Entry_Price": round(price, 2),
                    "Peak_Price": round(price, 2),
                    "Buy_Fee": buy_fee,
                    "Entry_Date": today_str
                })
                buy_rows.append([
                    f"**{get_name(b['Ticker'])}**（{short_ticker(b['Ticker'])}）｜"
                    f"{shares}股｜參考 {price:.2f}｜動能 {b['Momentum']*100:.1f}%",
                ])
        else:
            # 總資產太低，單檔預算不足
            buy_rows.append([
                f"**暫緩買進**｜單檔預算 {budget_per_stock:,.0f} < {MIN_BUDGET_THRESHOLD:,}",
            ])

    # --- 整理推播訊息與資產總結 ---
    if sell_rows:
        sell_msg = format_rows(row[0] for row in sell_rows)
    else:
        sell_msg = "✅ 目前無賣出訊號，安心抱牢。"
    if buy_rows:
        buy_msg = format_rows(row[0] for row in buy_rows)
    else:
        buy_msg = "⚠️ 今日無符合條件個股，或已達滿倉/大盤轉弱。"

    # 估算真實帳戶目前權益：只讀取帳戶與行情，不假設建議已成交。
    stock_value = 0
    for p in portfolio:
        if p["Ticker"] in signals:
            price = signals[p["Ticker"]]["Close"]
            gross_val = p["Shares"] * price
            est_sell_fee = calc_fee(gross_val)
            est_sell_tax = calc_tax(gross_val)
            stock_value += (gross_val - est_sell_fee - est_sell_tax)
            
    current_equity = cash + stock_value

    return account, current_equity, market_status, sell_msg, buy_msg, watchlist

# ==========================================
# 5. Discord 推播
# ==========================================
def build_discord_embed(account, current_equity, market_status, sell_msg, buy_msg, watchlist, account_label=""):
    portfolio = account["portfolio"]
    cash = account["cash"]

    if portfolio:
        rows = []
        for p in portfolio:
            ticker = p["Ticker"]
            rows.append([
                f"**{get_name(ticker)}**（{short_ticker(ticker)}）｜"
                f"{p['Shares']}股｜成本 {p['Entry_Price']:.2f}｜"
                f"高點 {p.get('Peak_Price', p['Entry_Price']):.2f}",
            ])
        table_str = format_rows(row[0] for row in rows)
        if len(table_str) > 1000:
            table_str = table_str[:1000] + "\n...（已截斷）"
    else:
        table_str = "目前空手，資金安全避險中。"

    invested_capital = float(account.get("invested_capital", INITIAL_CAPITAL))
    return_rate = ((current_equity - invested_capital) / invested_capital) * 100 if invested_capital > 0 else 0
    color = 65280 if return_rate >= 0 else 16711680

    embed = {
        "title": f"📈 量化分析：今日建議單{f'｜{account_label}' if account_label else ''}",
        "description": (
            f"**今日大盤環境：** {market_status}\n"
            f"以下內容只供決策參考，不會自動修改帳戶。實際成交後請用 bot 面板同步。"
        ),
        "color": color,
        "fields": [
            {
                "name": "📤 今日賣出建議",
                "value": sell_msg[:1024],
                "inline": False
            },
            {
                "name": "📥 今日買進建議",
                "value": buy_msg[:1024],
                "inline": False
            },
            {
                "name": "📊 目前持股",
                "value": table_str[:1024],
                "inline": False
            },
            {
                "name": "💰 帳戶摘要",
                "value": (
                    f"現金：**{cash:,.0f}**\n"
                    f"投入成本：**{invested_capital:,.0f}**\n"
                    f"估算總資產：**{current_equity:,.0f}**\n"
                    f"報酬率：**{return_rate:.2f}%**\n"
                    f"持股數：**{len(portfolio)}**"
                ),
                "inline": False
            }
        ],
        "footer": {
            "text": f"更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        }
    }

    return embed


def send_discord_msg(account, current_equity, market_status, sell_msg, buy_msg, watchlist):
    account_label = os.getenv("ACCOUNT_LABEL", "").strip()
    payload = {"embeds": [build_discord_embed(
        account,
        current_equity,
        market_status,
        sell_msg,
        buy_msg,
        watchlist,
        account_label,
    )]}

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info("Discord 訊息已送出")
    except Exception as e:
        logger.error(f"Discord 發送失敗：{e}")

# ==========================================
# 6. 主程式入口
# ==========================================
if __name__ == "__main__":
    if not DISCORD_WEBHOOK_URL:
        logger.error("❌ 請在 .env 檔中填入 DISCORD_WEBHOOK_URL")
    else:
        try:
            logger.info("===== 開始執行每日策略 =====")
            account, current_equity, market_status, sell_msg, buy_msg, watchlist = run_daily_strategy()
            send_discord_msg(account, current_equity, market_status, sell_msg, buy_msg, watchlist)
            logger.info(f"今日策略執行完成 | 總資產: {current_equity:,.0f}")
        except Exception as e:
            logger.error(f"程式錯誤：{e}\n{traceback.format_exc()}")
