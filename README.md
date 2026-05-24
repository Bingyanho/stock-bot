# Stock Trend Trader

台股趨勢動能策略工具，包含：

- `backtest.py`: 回測策略績效，輸出 `trade_log.csv`、`equity_curve.csv`、`backtest_result.png`
- `trend_trader.py`: 每日掃描股票池、讀取帳戶狀態、更新既有持股最高價、產生買賣建議並推播 Discord；不會寫入實際買賣
- `bot.py`: Discord 面板入口，可手動觸發策略與校正虛擬帳戶
- `config.py`: 共用參數、股票池、交易成本與 Discord 環境變數
- `account_store.py`: 帳戶資料讀寫與預設帳戶結構

## Setup

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env
```

編輯 `.env`，填入自己的 Discord credentials：

```dotenv
DISCORD_BOT_TOKEN=
ACCOUNTS_DIR=accounts
```

## Commands

執行回測：

```powershell
python backtest.py
```

執行每日策略與 Discord 推播。此程式會更新既有持股的 `Peak_Price` 供移動停利使用，但不會寫入買進、賣出、現金或冷卻狀態：

```powershell
python trend_trader.py
```

啟動 Discord bot：

```powershell
python bot.py
```

或雙擊：

```powershell
.\run_bot.bat
```

## Deployment

部署成長駐服務請看 [DEPLOYMENT.md](C:/Users/bingyan/OneDrive/stock/DEPLOYMENT.md)。目前已提供：

- `Dockerfile`
- `docker-compose.yml`
- `render.yaml`
- `Procfile`

正式部署時，請務必讓 `ACCOUNTS_DIR` 指向持久化磁碟，避免重新部署後使用者帳戶資料遺失。

## Discord Bot

所有 Discord 操作都集中在私人面板。啟動 bot 後，在 Discord 頻道輸入：

```text
run
```

bot 會把操作面板私訊給你；如果它有刪訊息權限，也會刪掉頻道裡的 `run`。也可以直接提到機器人來叫出私人面板。

私訊面板按鈕：

- `產生策略`: 手動執行 `trend_trader.py` 產生建議，不會修改帳戶。
- `買進`: 用真實成交價與股數同步買進。若原本沒有該持股，會直接新增持股並扣現金。
- `賣出`: 用真實成交價與股數同步賣出。股數留空或填 `0` 代表全數賣出。
- `現金`: 直接校正帳戶現金。
- `成本`: 設定報酬率使用的投入成本。策略推播會用 `估算總資產 ÷ 投入成本 - 1` 計算報酬率。
- `持股`: 直接同步持股數、成本價、最高價，不調整現金。股數填 `0` 代表移除該持股。
- `帳戶`: 查詢目前虛擬帳戶。

### 多使用者帳戶

Discord 面板會依照點按鈕的 Discord 使用者分開儲存帳戶：

- 每個使用者的帳戶檔在 `accounts/<discord_user_id>.json`
- 使用者 A 的買進、賣出、現金、成本、持股同步，不會影響使用者 B
- 按「產生策略」時，`trend_trader.py` 會用該使用者自己的帳戶產生建議
- 直接在命令列執行 `python trend_trader.py` 時，仍會使用舊的單人帳戶檔 `trading_account.json`

## Notes

- `.env`、`trading_account.json`、`accounts/`、log 檔與回測輸出已放在 `.gitignore`。
- `trend_trader.py` 只會維護既有持股的 `Peak_Price`；所有真實買賣、現金與持股同步都由 `bot.py` 完成。
- 報酬率分母由帳戶欄位 `invested_capital` 決定，可在 Discord 面板按「成本」修改。
- 實盤操作前，請先確認 Discord token/webhook 已經換成新的，舊的外洩密鑰應在 Discord 後台撤銷。
- 回測結果可能受到資料源、除權息、滑價、股票池與倖存者偏誤影響，請勿直接視為未來績效保證。
