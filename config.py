import os

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv() -> bool:
        if not os.path.exists(".env"):
            return False

        with open(".env", "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return False

load_dotenv()

# Files
DB_FILE = "trading_account.json"
WATCHLIST_FILE = "watchlist.txt"

# Secrets
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()

# Portfolio settings
INITIAL_CAPITAL = 200000
MAX_POSITIONS = 5
POSITION_SIZE = 1.0 / MAX_POSITIONS
MIN_BUDGET_THRESHOLD = 10000
BENCHMARK = "0050.TW"

# Strategy settings
MOMENTUM_DAYS = 10
EXIT_BUFFER = 0.99
STOP_LOSS_BUFFER = 0.92
TRAILING_STOP_BUFFER = 0.90
MIN_HOLD_DAYS = 5
COOLDOWN_DAYS = 3
TARGET_WATCHLIST_SIZE = 20
MIN_MOMENTUM_THRESHOLD = 0.05

# Transaction costs
FEE_RATE = 0.001425
FEE_DISCOUNT = 0.6
TAX_RATE = 0.003
MIN_FEE = 20
SLIPPAGE = 0.001

# Backtest range
START_DATE = "2018-01-01"
END_DATE = None

STOCK_NAMES = {
    "2330.TW": "台積電", "2317.TW": "鴻海", "2454.TW": "聯發科", "2308.TW": "台達電", "2382.TW": "廣達",
    "2881.TW": "富邦金", "2882.TW": "國泰金", "2412.TW": "中華電", "1216.TW": "統一", "2002.TW": "中鋼",
    "2303.TW": "聯電", "3231.TW": "緯創", "3008.TW": "大立光", "2603.TW": "長榮", "2324.TW": "仁寶",
    "3034.TW": "聯詠", "3481.TW": "群創", "2409.TW": "友達", "1101.TW": "台泥", "1102.TW": "亞泥",
    "1301.TW": "台塑", "1303.TW": "南亞", "2886.TW": "兆豐金", "2891.TW": "中信金", "2892.TW": "第一金",
    "2357.TW": "華碩", "2379.TW": "瑞昱", "3293.TWO": "鈊象", "8299.TWO": "群聯", "2376.TW": "技嘉",
    "3661.TW": "世芯-KY", "1504.TW": "東元", "1519.TW": "華城", "1605.TW": "大亞", "2609.TW": "陽明",
    "2615.TW": "萬海", "3017.TW": "奇鋐", "3037.TW": "欣興", "2395.TW": "研華", "3529.TWO": "力旺",
    "2368.TW": "金像電", "6669.TW": "緯穎", "2383.TW": "台光電", "3044.TW": "健鼎",
    "5347.TWO": "世界", "5483.TWO": "中美晶", "6274.TWO": "台燿",
}

SCAN_UNIVERSE = list(STOCK_NAMES.keys())


def get_name(ticker: str) -> str:
    return STOCK_NAMES.get(ticker, ticker)


def calc_fee(amount: float) -> int:
    return max(MIN_FEE, int(amount * FEE_RATE * FEE_DISCOUNT))


def calc_tax(amount: float) -> int:
    return int(amount * TAX_RATE)
