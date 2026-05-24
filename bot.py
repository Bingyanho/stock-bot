import discord
from discord.ext import commands
import asyncio
import logging
import re
from datetime import datetime

from account_store import load_account, save_account
from config import COOLDOWN_DAYS, DISCORD_BOT_TOKEN, STOCK_NAMES, calc_fee, calc_tax, get_name

# ==========================================
# 1. 設定區
# ==========================================
TOKEN = DISCORD_BOT_TOKEN

# 日誌設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 設定 Bot 的權限
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=commands.when_mentioned_or("!", "$"), intents=intents)
bot.remove_command("help")
panel_view_registered = False

# ==========================================
# 2. 工具函數
# ==========================================
def user_account_id(user) -> str:
    return str(user.id)


def user_label(user) -> str:
    return getattr(user, "display_name", None) or getattr(user, "name", "unknown")


def normalize_ticker(ticker: str) -> str:
    ticker = ticker.upper().strip()
    if "." not in ticker:
        tw_ticker = f"{ticker}.TW"
        two_ticker = f"{ticker}.TWO"
        if tw_ticker in STOCK_NAMES:
            return tw_ticker
        if two_ticker in STOCK_NAMES:
            return two_ticker
        return tw_ticker
    return ticker


def require_stock_pool_ticker(ticker: str) -> str:
    ticker = normalize_ticker(ticker)
    if ticker not in STOCK_NAMES:
        raise ValueError(f"{ticker} 不在目前股票池中，無法買進。")
    return ticker


def find_position(account: dict, ticker: str) -> dict | None:
    for pos in account.get("portfolio", []):
        if pos.get("Ticker") == ticker:
            return pos
    return None


def today_str() -> str:
    return datetime.today().strftime("%Y-%m-%d")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def account_summary(account: dict) -> str:
    portfolio = account.get("portfolio", [])
    msg = (
        f"投入成本：{account.get('invested_capital', 0):,.0f} 元\n"
        f"可用現金：{account.get('cash', 0):,.0f} 元\n"
        f"持股數：{len(portfolio)}\n"
    )
    if not portfolio:
        return msg + "目前無持股。"

    msg += "\n持股：\n"
    for p in portfolio:
        msg += (
            f"- {p.get('Name', p['Ticker'])} ({p['Ticker']}): "
            f"{p['Shares']} 股 @ {p['Entry_Price']}，高點 {p.get('Peak_Price', p['Entry_Price'])}\n"
        )
    return msg


def holdings_summary(account: dict) -> str:
    portfolio = account.get("portfolio", [])
    if not portfolio:
        return "目前無持股。"

    lines = []
    for p in portfolio:
        ticker = p.get("Ticker", "")
        lines.append(
            f"- {p.get('Name') or get_name(ticker)}（{ticker}）｜"
            f"{p.get('Shares', 0)}股｜成本 {float(p.get('Entry_Price', 0)):.2f}｜"
            f"高點 {float(p.get('Peak_Price', p.get('Entry_Price', 0))):.2f}"
        )
    return "\n".join(lines)


def append_trade(account: dict, trade: dict) -> None:
    account.setdefault("trades", []).append({
        "Time": now_str(),
        **trade,
    })


def trade_history_summary(account: dict, limit: int = 10) -> str:
    trades = account.get("trades", [])
    if not trades:
        return "目前沒有交易紀錄。"

    lines = []
    for trade in trades[-limit:][::-1]:
        side = "買進" if trade.get("Side") == "BUY" else "賣出"
        ticker = trade.get("Ticker", "")
        name = trade.get("Name") or get_name(ticker)
        shares = int(trade.get("Shares", 0))
        price = float(trade.get("Price", 0))
        time = trade.get("Time", "")
        cash_after = float(trade.get("Cash_After", 0))
        if trade.get("Side") == "SELL":
            pnl = float(trade.get("Pnl", 0))
            pnl_pct = float(trade.get("Pnl_Pct", 0))
            lines.append(
                f"{time}｜{side} {name}（{ticker}）｜{shares}股 @ {price:.2f}｜"
                f"損益 {pnl:,.0f} ({pnl_pct:.2f}%)｜現金 {cash_after:,.0f}"
            )
        else:
            total_cost = float(trade.get("Total_Cost", 0))
            lines.append(
                f"{time}｜{side} {name}（{ticker}）｜{shares}股 @ {price:.2f}｜"
                f"成本 {total_cost:,.0f}｜現金 {cash_after:,.0f}"
            )

    return "\n".join(lines)


def sync_buy(account_id: str, ticker: str, real_price: float, real_shares: int) -> str:
    ticker = require_stock_pool_ticker(ticker)
    if real_price <= 0 or real_shares <= 0:
        raise ValueError("價格與股數都必須大於 0。")

    account = load_account(account_id)
    pos = find_position(account, ticker)

    gross = real_price * real_shares
    fee = calc_fee(gross)
    total_cost = gross + fee

    if pos:
        old_cost = pos["Shares"] * pos["Entry_Price"] + pos.get("Buy_Fee", 0)
        account["cash"] += old_cost
        action = "修正"
    else:
        pos = {
            "Ticker": ticker,
            "Name": get_name(ticker),
            "Entry_Date": today_str(),
        }
        account.setdefault("portfolio", []).append(pos)
        action = "新增"

    pos.update({
        "Ticker": ticker,
        "Name": get_name(ticker),
        "Shares": real_shares,
        "Entry_Price": real_price,
        "Peak_Price": max(real_price, pos.get("Peak_Price", real_price)),
        "Buy_Fee": fee,
        "Entry_Date": pos.get("Entry_Date", today_str()),
    })
    account["cash"] -= total_cost
    append_trade(account, {
        "Side": "BUY",
        "Ticker": ticker,
        "Name": get_name(ticker),
        "Shares": real_shares,
        "Price": real_price,
        "Gross": gross,
        "Fee": fee,
        "Tax": 0,
        "Total_Cost": total_cost,
        "Cash_After": account["cash"],
        "Action": action,
    })
    save_account(account, account_id)
    return (
        f"✅ 買進已同步｜{action} {get_name(ticker)}（{ticker}）\n"
        f"{real_shares}股 @ {real_price:.2f}｜現金 {account['cash']:,.0f}"
    )


def preview_buy(account_id: str, ticker: str, real_price: float, real_shares: int) -> tuple[str, str]:
    ticker = require_stock_pool_ticker(ticker)
    if real_price <= 0 or real_shares <= 0:
        raise ValueError("價格與股數都必須大於 0。")

    account = load_account(account_id)
    pos = find_position(account, ticker)
    gross = real_price * real_shares
    fee = calc_fee(gross)
    total_cost = gross + fee
    current_cash = float(account.get("cash", 0))
    old_cost = pos["Shares"] * pos["Entry_Price"] + pos.get("Buy_Fee", 0) if pos else 0
    projected_cash = current_cash + old_cost - total_cost
    action = "修正既有持股" if pos else "新增持股"
    msg = (
        f"請確認買進同步\n\n"
        f"股票：{get_name(ticker)}（{ticker}）\n"
        f"動作：{action}\n"
        f"股數：{real_shares}\n"
        f"價格：{real_price:.2f}\n"
        f"手續費：{fee:,.0f}\n"
        f"總成本：{total_cost:,.0f}\n"
        f"同步後現金：{projected_cash:,.0f}"
    )
    return ticker, msg


def sync_sell(account_id: str, ticker: str, real_price: float, real_shares: int = 0) -> str:
    ticker = normalize_ticker(ticker)
    if real_price <= 0:
        raise ValueError("價格必須大於 0。")

    account = load_account(account_id)
    pos = find_position(account, ticker)
    if not pos:
        raise ValueError(f"找不到 {ticker} 的持倉紀錄。")

    held_shares = int(pos.get("Shares", 0))
    sell_shares = held_shares if real_shares <= 0 else real_shares
    if sell_shares <= 0 or sell_shares > held_shares:
        raise ValueError(f"賣出股數不正確，目前持有 {held_shares} 股。")

    gross = real_price * sell_shares
    fee = calc_fee(gross)
    tax = calc_tax(gross)
    net = gross - fee - tax
    account["cash"] += net

    entry_price = float(pos.get("Entry_Price", 0))
    buy_fee = int(pos.get("Buy_Fee", 0))
    allocated_buy_fee = int(round(buy_fee * sell_shares / held_shares)) if held_shares else 0
    cost_basis = entry_price * sell_shares + allocated_buy_fee
    pnl = net - cost_basis
    pnl_pct = pnl / cost_basis * 100 if cost_basis > 0 else 0

    remaining = held_shares - sell_shares
    if remaining == 0:
        account["portfolio"] = [p for p in account.get("portfolio", []) if p.get("Ticker") != ticker]
        account.setdefault("cooldowns", {})[ticker] = today_str()
        action = f"已全數賣出，進入 {COOLDOWN_DAYS} 天冷卻"
    else:
        pos["Shares"] = remaining
        pos["Buy_Fee"] = max(0, buy_fee - allocated_buy_fee)
        action = f"部分賣出，剩餘 {remaining} 股"

    append_trade(account, {
        "Side": "SELL",
        "Ticker": ticker,
        "Name": get_name(ticker),
        "Shares": sell_shares,
        "Price": real_price,
        "Gross": gross,
        "Fee": fee,
        "Tax": tax,
        "Net": net,
        "Cost_Basis": cost_basis,
        "Pnl": pnl,
        "Pnl_Pct": pnl_pct,
        "Cash_After": account["cash"],
        "Action": action,
    })
    save_account(account, account_id)
    status = "全賣" if remaining == 0 else f"剩 {remaining}股"
    return (
        f"✅ 賣出已同步｜{get_name(ticker)}（{ticker}）｜{status}\n"
        f"{sell_shares}股 @ {real_price:.2f}｜損益 {pnl:,.0f} ({pnl_pct:.2f}%)｜現金 {account['cash']:,.0f}"
    )


def preview_sell(account_id: str, ticker: str, real_price: float, real_shares: int = 0) -> tuple[str, int, str]:
    ticker = normalize_ticker(ticker)
    if real_price <= 0:
        raise ValueError("價格必須大於 0。")

    account = load_account(account_id)
    pos = find_position(account, ticker)
    if not pos:
        raise ValueError(f"找不到 {ticker} 的持倉紀錄。")

    held_shares = int(pos.get("Shares", 0))
    sell_shares = held_shares if real_shares <= 0 else real_shares
    if sell_shares <= 0 or sell_shares > held_shares:
        raise ValueError(f"賣出股數不正確，目前持有 {held_shares} 股。")

    gross = real_price * sell_shares
    fee = calc_fee(gross)
    tax = calc_tax(gross)
    net = gross - fee - tax
    entry_price = float(pos.get("Entry_Price", 0))
    buy_fee = int(pos.get("Buy_Fee", 0))
    allocated_buy_fee = int(round(buy_fee * sell_shares / held_shares)) if held_shares else 0
    cost_basis = entry_price * sell_shares + allocated_buy_fee
    pnl = net - cost_basis
    pnl_pct = pnl / cost_basis * 100 if cost_basis > 0 else 0
    projected_cash = float(account.get("cash", 0)) + net
    status = "全賣" if sell_shares == held_shares else f"部分賣出，賣後剩 {held_shares - sell_shares} 股"
    msg = (
        f"請確認賣出同步\n\n"
        f"股票：{get_name(ticker)}（{ticker}）\n"
        f"動作：{status}\n"
        f"股數：{sell_shares}\n"
        f"價格：{real_price:.2f}\n"
        f"手續費：{fee:,.0f}\n"
        f"證交稅：{tax:,.0f}\n"
        f"預估損益：{pnl:,.0f} ({pnl_pct:.2f}%)\n"
        f"同步後現金：{projected_cash:,.0f}"
    )
    return ticker, sell_shares, msg


def sync_cash(account_id: str, new_cash: float) -> str:
    account = load_account(account_id)
    old_cash = account.get("cash", 0)
    account["cash"] = new_cash
    save_account(account, account_id)
    return f"✅ 現金已更新｜{old_cash:,.0f} → {new_cash:,.0f}"


def sync_invested_capital(account_id: str, new_cost: float) -> str:
    if new_cost <= 0:
        raise ValueError("投入成本必須大於 0。")

    account = load_account(account_id)
    old_cost = account.get("invested_capital", 0)
    account["invested_capital"] = new_cost
    save_account(account, account_id)
    return f"✅ 投入成本已更新｜{old_cost:,.0f} → {new_cost:,.0f}"


def sync_holding(account_id: str, ticker: str, shares: int, entry_price: float, peak_price: float = 0) -> str:
    ticker = normalize_ticker(ticker)
    account = load_account(account_id)
    pos = find_position(account, ticker)

    if shares <= 0:
        account["portfolio"] = [p for p in account.get("portfolio", []) if p.get("Ticker") != ticker]
        save_account(account, account_id)
        return f"✅ 持股已移除｜{get_name(ticker)}（{ticker}）"

    if entry_price <= 0:
        raise ValueError("成本價必須大於 0。")

    if not pos:
        pos = {"Ticker": ticker, "Entry_Date": today_str()}
        account.setdefault("portfolio", []).append(pos)

    gross = entry_price * shares
    pos.update({
        "Ticker": ticker,
        "Name": get_name(ticker),
        "Shares": shares,
        "Entry_Price": entry_price,
        "Peak_Price": peak_price if peak_price > 0 else max(entry_price, pos.get("Peak_Price", entry_price)),
        "Buy_Fee": calc_fee(gross),
        "Entry_Date": pos.get("Entry_Date", today_str()),
    })
    save_account(account, account_id)
    return (
        f"✅ 持股已同步｜{get_name(ticker)}（{ticker}）\n"
        f"{shares}股｜成本 {entry_price:.2f}｜高點 {pos['Peak_Price']:.2f}"
    )


async def run_strategy_and_send(send, user):
    await send("🚀 正在產生策略建議...")

    def run_strategy():
        from trend_trader import build_discord_embed, run_daily_strategy

        result = run_daily_strategy(user_account_id(user))
        account, current_equity, market_status, sell_msg, buy_msg, watchlist = result
        return build_discord_embed(
            account,
            current_equity,
            market_status,
            sell_msg,
            buy_msg,
            watchlist,
            user_label(user),
        )

    try:
        embed_data = await asyncio.to_thread(run_strategy)
        await send(
            embed=discord.Embed.from_dict(build_strategy_summary_embed(embed_data)),
            view=StrategyDetailView(user.id, embed_data),
        )
    except Exception as e:
        logger.error(f"策略執行失敗：{e}")
        await send(f"❌ **策略執行失敗：** {e}")


def extract_stock_names(text: str) -> list[str]:
    known_names = set(STOCK_NAMES.values())
    names = []
    for name in re.findall(r"\*\*(.*?)\*\*", text or ""):
        clean = name.strip()
        if clean in known_names and clean not in names:
            names.append(clean)
    return names


def summarize_signal_text(text: str) -> str:
    names = extract_stock_names(text)
    return "、".join(names) if names else "無"


def build_strategy_summary_embed(embed_data: dict) -> dict:
    fields = embed_data.get("fields", [])
    sell_value = fields[0]["value"] if len(fields) > 0 else ""
    buy_value = fields[1]["value"] if len(fields) > 1 else ""
    return {
        "title": embed_data.get("title", "今日策略建議"),
        "description": embed_data.get("description", ""),
        "color": embed_data.get("color", 0x2F80ED),
        "fields": [
            {
                "name": "賣出建議",
                "value": summarize_signal_text(sell_value),
                "inline": False,
            },
            {
                "name": "買進建議",
                "value": summarize_signal_text(buy_value),
                "inline": False,
            },
        ],
        "footer": embed_data.get("footer", {}),
    }


class StrategyDetailView(discord.ui.View):
    def __init__(self, owner_id: int, embed_data: dict):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.embed_data = embed_data

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("這是別人的策略面板。", ephemeral=True)
            return False
        return True

    def field_value(self, index: int) -> str:
        fields = self.embed_data.get("fields", [])
        if index >= len(fields):
            return "無資料。"
        return fields[index].get("value") or "無資料。"

    async def send_detail(self, interaction: discord.Interaction, title: str, index: int):
        embed = discord.Embed(
            title=title,
            description=self.field_value(index)[:4096],
            color=self.embed_data.get("color", 0x2F80ED),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="賣出詳情", style=discord.ButtonStyle.secondary)
    async def sell_detail(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_detail(interaction, "賣出建議詳情", 0)

    @discord.ui.button(label="買進詳情", style=discord.ButtonStyle.secondary)
    async def buy_detail(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_detail(interaction, "買進建議詳情", 1)

    @discord.ui.button(label="持股與帳戶", style=discord.ButtonStyle.secondary)
    async def account_detail(self, interaction: discord.Interaction, button: discord.ui.Button):
        fields = self.embed_data.get("fields", [])
        holdings = fields[2].get("value", "無資料。") if len(fields) > 2 else "無資料。"
        account = fields[3].get("value", "無資料。") if len(fields) > 3 else "無資料。"
        embed = discord.Embed(
            title="持股與帳戶摘要",
            description=f"{holdings[:1800]}\n\n{account[:1800]}",
            color=self.embed_data.get("color", 0x2F80ED),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


def parse_float(value: str, field_name: str) -> float:
    try:
        return float(value.strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} 必須是數字。") from exc


def parse_int(value: str, field_name: str) -> int:
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} 必須是整數。") from exc


class ConfirmBuyView(discord.ui.View):
    def __init__(self, owner_id: int, account_id: str, ticker: str, price: float, shares: int):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.account_id = account_id
        self.ticker = ticker
        self.price = price
        self.shares = shares

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("這不是你的確認訊息。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="確認同步", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            msg = sync_buy(self.account_id, self.ticker, self.price, self.shares)
            await interaction.response.edit_message(content=msg, view=None)
        except ValueError as e:
            await interaction.response.edit_message(content=f"⚠️ {e}", view=None)

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="已取消買進同步。", view=None)


class ConfirmSellView(discord.ui.View):
    def __init__(self, owner_id: int, account_id: str, ticker: str, price: float, shares: int):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.account_id = account_id
        self.ticker = ticker
        self.price = price
        self.shares = shares

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("這不是你的確認訊息。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="確認同步", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            msg = sync_sell(self.account_id, self.ticker, self.price, self.shares)
            await interaction.response.edit_message(content=msg, view=None)
        except ValueError as e:
            await interaction.response.edit_message(content=f"⚠️ {e}", view=None)

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="已取消賣出同步。", view=None)


class BuyModal(discord.ui.Modal, title="同步買進成交"):
    ticker = discord.ui.TextInput(label="股票名稱 / 代號", placeholder="例如 2330、6274 或 2330.TW")
    shares = discord.ui.TextInput(label="股數", placeholder="例如 100")
    price = discord.ui.TextInput(label="成交價格", placeholder="例如 850")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            account_id = user_account_id(interaction.user)
            price = parse_float(str(self.price), "成交價")
            shares = parse_int(str(self.shares), "股數")
            ticker, msg = preview_buy(
                account_id,
                str(self.ticker),
                price,
                shares,
            )
            await interaction.response.send_message(
                msg,
                view=ConfirmBuyView(interaction.user.id, account_id, ticker, price, shares),
                ephemeral=True,
            )
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)


class SellModal(discord.ui.Modal, title="同步賣出成交"):
    ticker = discord.ui.TextInput(label="股票名稱 / 代號", placeholder="例如 2330、6274 或 2330.TW")
    shares = discord.ui.TextInput(
        label="股數",
        placeholder="例如 100；留空或填 0 代表全賣",
        required=False,
    )
    price = discord.ui.TextInput(label="成交價格", placeholder="例如 900")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            share_text = str(self.shares).strip()
            account_id = user_account_id(interaction.user)
            price = parse_float(str(self.price), "成交價")
            shares = parse_int(share_text, "股數") if share_text else 0
            ticker, sell_shares, msg = preview_sell(
                account_id,
                str(self.ticker),
                price,
                shares,
            )
            await interaction.response.send_message(
                msg,
                view=ConfirmSellView(interaction.user.id, account_id, ticker, price, sell_shares),
                ephemeral=True,
            )
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)


class CashModal(discord.ui.Modal, title="校正帳戶現金"):
    cash = discord.ui.TextInput(label="目前可用現金", placeholder="例如 150000")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            msg = sync_cash(user_account_id(interaction.user), parse_float(str(self.cash), "現金"))
            await interaction.response.send_message(msg)
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)


class CostModal(discord.ui.Modal, title="設定投入成本"):
    cost = discord.ui.TextInput(label="最初投入成本 / 報酬率分母", placeholder="例如 200000")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            msg = sync_invested_capital(user_account_id(interaction.user), parse_float(str(self.cost), "投入成本"))
            await interaction.response.send_message(msg)
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)


class HoldingModal(discord.ui.Modal, title="同步持股"):
    ticker = discord.ui.TextInput(label="股票名稱 / 代號", placeholder="例如 2330、6274 或 2330.TW")
    shares = discord.ui.TextInput(label="股數", placeholder="例如 100；填 0 代表移除持股")
    entry_price = discord.ui.TextInput(label="成本價格", placeholder="例如 850；移除持股時可填 0")
    peak_price = discord.ui.TextInput(
        label="最高價格",
        placeholder="例如 900；可留空，預設使用成本價",
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            peak_text = str(self.peak_price).strip()
            msg = sync_holding(
                user_account_id(interaction.user),
                str(self.ticker),
                parse_int(str(self.shares), "股數"),
                parse_float(str(self.entry_price), "成本價"),
                parse_float(peak_text, "最高價") if peak_text else 0,
            )
            await interaction.response.send_message(msg)
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)


class StrategyPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="產生策略", style=discord.ButtonStyle.primary, custom_id="stock_bot:run_strategy")
    async def run_strategy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("收到，開始分析。", ephemeral=True)
        await run_strategy_and_send(interaction.followup.send, interaction.user)


class AccountSyncPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="買進", style=discord.ButtonStyle.success, custom_id="stock_bot:buy")
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BuyModal())

    @discord.ui.button(label="賣出", style=discord.ButtonStyle.danger, custom_id="stock_bot:sell")
    async def sell(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SellModal())

    @discord.ui.button(label="同步持股", style=discord.ButtonStyle.secondary, custom_id="stock_bot:holding")
    async def holding(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(HoldingModal())


class AccountSettingsPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="修改現金", style=discord.ButtonStyle.secondary, custom_id="stock_bot:cash")
    async def cash(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CashModal())

    @discord.ui.button(label="修改投入成本", style=discord.ButtonStyle.secondary, custom_id="stock_bot:cost")
    async def cost(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CostModal())


class QueryPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="帳戶總覽", style=discord.ButtonStyle.secondary, custom_id="stock_bot:account")
    async def account(self, interaction: discord.Interaction, button: discord.ui.Button):
        account = load_account(user_account_id(interaction.user))
        await interaction.response.send_message(
            f"💰 **{user_label(interaction.user)} 的帳戶狀態**\n{account_summary(account)}",
            ephemeral=True,
        )

    @discord.ui.button(label="目前持股", style=discord.ButtonStyle.secondary, custom_id="stock_bot:holdings")
    async def holdings(self, interaction: discord.Interaction, button: discord.ui.Button):
        account = load_account(user_account_id(interaction.user))
        await interaction.response.send_message(
            f"📊 **目前持股**\n{holdings_summary(account)}",
            ephemeral=True,
        )

    @discord.ui.button(label="交易紀錄", style=discord.ButtonStyle.secondary, custom_id="stock_bot:trades")
    async def trades(self, interaction: discord.Interaction, button: discord.ui.Button):
        account = load_account(user_account_id(interaction.user))
        await interaction.response.send_message(
            f"📒 **最近交易紀錄**\n{trade_history_summary(account)}",
            ephemeral=True,
        )


class ConsolePanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="控制台", style=discord.ButtonStyle.primary, custom_id="stock_bot:console")
    async def console(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("已重新開啟控制台。", ephemeral=True)
        await send_panel(interaction.user)

# ==========================================
# 3. 面板入口
# ==========================================
PANEL_TRIGGERS = {"run"}


def panel_block(title: str, description: str = "") -> str:
    body = f"**{title}**"
    if description:
        body += f"\n{description}"
    return f"━━━━━━━━━━━━\n{body}"


async def send_panel(user):
    await user.send(
        panel_block("股票帳戶操作面板", "策略只提供建議；實際成交請用面板同步。"),
        view=ConsolePanel(),
    )
    await user.send(
        panel_block("策略"),
        view=StrategyPanel(),
    )
    await user.send(
        panel_block("帳戶同步"),
        view=AccountSyncPanel(),
    )
    await user.send(
        panel_block("帳戶設定"),
        view=AccountSettingsPanel(),
    )
    await user.send(
        panel_block("查詢"),
        view=QueryPanel(),
    )


@bot.event
async def on_ready():
    global panel_view_registered
    if not panel_view_registered:
        bot.add_view(ConsolePanel())
        bot.add_view(StrategyPanel())
        bot.add_view(AccountSyncPanel())
        bot.add_view(AccountSettingsPanel())
        bot.add_view(QueryPanel())
        panel_view_registered = True
    print(f"✅ 機器人 {bot.user} 已上線。輸入「run」即可開啟操作介面。")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.strip().lower()
    mentioned_bot = bot.user and bot.user in message.mentions
    if content in PANEL_TRIGGERS or mentioned_bot:
        try:
            await send_panel(message.author)
            if message.guild:
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass
        except discord.Forbidden:
            logger.warning(f"無法私訊使用者：{message.author}")

if __name__ == "__main__":
    if not TOKEN:
        logger.error("❌ 請在 .env 檔中填入 DISCORD_BOT_TOKEN")
    else:
        bot.run(TOKEN)
