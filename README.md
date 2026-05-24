# Stock Bot

Discord 私訊面板版台股量化交易助理。系統會每天掃描股票池、依趨勢與動能產生買賣建議，實際成交後由使用者在 Discord 私訊面板同步帳戶。

目前部署方式：Google Cloud VM + Docker Compose。

## 功能

- 每位 Discord 使用者都有獨立帳戶。
- 在 Discord 頻道輸入 `run`，bot 會私訊私人操作面板。
- 面板支援：
  - `產生策略`: 掃描股票池並產生今日建議。
  - `買進`: 用真實成交價與股數同步買進。
  - `賣出`: 用真實成交價與股數同步賣出。
  - `現金`: 校正可用現金。
  - `成本`: 設定報酬率分母，也就是投入成本。
  - `同步持股`: 直接同步持股數、成本價、最高價。
  - `帳戶`: 查詢自己的帳戶狀態。
- `trend_trader.py` 不會自動寫入買賣結果，只會維護既有持股的 `Peak_Price`。

## 專案檔案

- `bot.py`: Discord bot 與私訊操作面板。
- `trend_trader.py`: 策略掃描、建議產生、Discord embed 格式。
- `account_store.py`: 多使用者帳戶讀寫。
- `config.py`: 股票池、策略參數、交易成本、環境變數。
- `backtest.py`: 策略回測。
- `Dockerfile`: 部署用 Docker image。
- `docker-compose.yml`: VM 上長駐執行 bot。
- `DEPLOYMENT.md`: 其他部署參考。

## 環境變數

正式部署只需要：

```dotenv
DISCORD_BOT_TOKEN=你的 Discord Bot Token
ACCOUNTS_DIR=accounts
```

`.env` 不要 commit 到 GitHub。

## 本機執行

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env
python bot.py
```

執行回測：

```powershell
python backtest.py
```

## VM 部署

目前 VM 上的專案位置建議為：

```bash
~/stock
```

第一次部署：

```bash
cd ~
git clone https://github.com/Bingyanho/stock-bot.git stock
cd stock
cp .env.example .env
nano .env
docker compose up -d --build
```

查看 log：

```bash
docker compose logs -f
```

看到以下訊息代表 bot 已上線：

```text
機器人 <name> 已上線。輸入「run」即可開啟操作介面。
```

## Discord 使用方式

在 bot 可以讀取訊息的頻道輸入：

```text
run
```

bot 會私訊你的操作面板。如果 bot 有刪除訊息權限，會刪除頻道裡的 `run`。

如果沒有收到私訊，請確認：

- Discord 使用者允許伺服器成員私訊。
- bot 有 `Message Content Intent`。
- bot 有讀取頻道訊息權限。

## 多使用者帳戶

每個 Discord 使用者會有自己的帳戶檔：

```text
accounts/<discord_user_id>.json
```

使用者之間互不影響。部署時 `accounts/` 必須保留在 VM 上，不要刪除。

## 修改程式後重新部署

### 1. 本機修改程式

在 Windows 本機：

```powershell
cd C:\Users\bingyan\OneDrive\stock
```

修改程式後先測試：

```powershell
python -m py_compile bot.py trend_trader.py account_store.py config.py backtest.py tests\test_config.py
python -m unittest discover -s tests
```

### 2. Commit 並推到 GitHub

```powershell
git status
git add .
git commit -m "Describe your change"
git push
```

注意：`.env`、`accounts/`、log、回測輸出都在 `.gitignore`，不應該被推上去。

### 3. 到 VM 拉最新版並重啟

在 Google Cloud VM SSH：

```bash
cd ~/stock
git pull
docker compose up -d --build
docker compose logs -f
```

如果只改 README 或文件，不需要重啟 bot；如果改 `bot.py`、`trend_trader.py`、`config.py`、`account_store.py`，就要重新 build/restart。

## 常用維護指令

查看服務狀態：

```bash
docker compose ps
```

看 log：

```bash
docker compose logs -f
```

重啟：

```bash
docker compose restart
```

停止：

```bash
docker compose down
```

重新 build：

```bash
docker compose up -d --build
```

## 備份帳戶資料

帳戶資料在 VM 的：

```bash
~/stock/accounts
```

建議定期備份：

```bash
cd ~/stock
tar -czf accounts-backup-$(date +%Y%m%d).tar.gz accounts
```

## 注意

- 本系統只提供量化建議，不保證獲利。
- yfinance 資料可能延遲、缺漏或受除權息資料影響。
- `trend_trader.py` 只會更新持股最高價 `Peak_Price`，實際買賣必須由使用者在 Discord 面板同步。
- `DISCORD_WEBHOOK_URL` 目前不是主流程需要的環境變數；私訊面板不使用 webhook。
