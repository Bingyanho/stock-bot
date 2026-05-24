# Stock Bot

這是一套 Discord 股票帳戶同步與量化策略提醒系統，主要用來管理台股持股、現金、投入成本，並產生每日策略建議。

目前版本的核心原則：

- Discord 使用者輸入 `run` 呼叫私訊操作面板。
- 所有帳戶操作都在 Discord 面板完成，不再依賴文字指令。
- 每個 Discord 使用者有自己的帳戶檔案。
- `trend_trader.py` 只讀取帳戶並產生策略建議，不會自動買進、賣出、改現金或改成本。
- 策略執行時仍會更新既有持股的 `Peak_Price`，用於移動停利判斷。
- 市場資料來源採用「FinMind 優先，yfinance 備援」。

## 功能

- 私訊操作面板
  - 控制台：重新開啟整套面板
  - 策略：產生今日建議
  - 帳戶同步：買進、賣出、同步持股
  - 帳戶設定：修改現金、修改投入成本
  - 查詢：帳戶總覽、目前持股、交易紀錄
- 多使用者帳戶
  - 帳戶資料存在 `accounts/<discord_user_id>.json`
  - 不同使用者互不影響
- 台股代號補全
  - 已知上市股票會補成 `.TW`
  - 已知上櫃股票會補成 `.TWO`
  - 例如輸入 `6274` 會自動辨識為 `6274.TWO`
- 量化策略建議
  - 掃描股票池
  - 更新 watchlist
  - 第一頁只列買進與賣出股票名稱
  - 詳細買賣建議、持股與帳戶資訊用按鈕展開
  - 不直接修改實際帳戶交易紀錄
- 交易紀錄
  - 確認同步買進或賣出後自動寫入
  - 記錄成交時間、股票、股數、價格、手續費、稅金、損益與同步後現金

## 資料來源

資料取得集中在 `data_provider.py`。

流程是：

1. 先用 FinMind 取得台股 OHLC 資料。
2. 單一股票 FinMind 失敗時，該股票改用 yfinance 備援。
3. 如果 FinMind 與 yfinance 都失敗，才會讓策略或回測停止並顯示錯誤。

`FINMIND_TOKEN` 建議設定。沒有 token 時系統仍會先嘗試 FinMind，再使用 yfinance 備援，但穩定性可能較差。

## 專案檔案

- `bot.py`：Discord bot、私訊面板、所有實際帳戶操作
- `trend_trader.py`：量化策略、策略回報、更新持股高點
- `data_provider.py`：FinMind 優先、yfinance 備援的資料取得層
- `account_store.py`：多使用者帳戶讀寫
- `config.py`：股票池、參數、股票名稱、環境變數
- `backtest.py`：策略回測
- `Dockerfile`：部署用 Docker image
- `docker-compose.yml`：Google Cloud VM 上長期執行 bot
- `DEPLOYMENT.md`：部署補充說明

## 環境變數

複製 `.env.example` 成 `.env`：

```bash
cp .env.example .env
```

`.env` 範例：

```dotenv
DISCORD_BOT_TOKEN=你的 Discord Bot Token
FINMIND_TOKEN=你的 FinMind Token
ACCOUNTS_DIR=accounts
```

說明：

- `DISCORD_BOT_TOKEN`：必要。
- `FINMIND_TOKEN`：建議設定，用於提高 FinMind 穩定性。
- `ACCOUNTS_DIR`：帳戶資料資料夾，本機通常用 `accounts`，Docker 內使用 `/app/accounts`。

不要把 `.env` commit 到 GitHub。

## 本機執行

```powershell
cd C:\Users\bingyan\OneDrive\stock
pip install -r requirements.txt
Copy-Item .env.example .env
python bot.py
```

回測：

```powershell
python backtest.py
```

測試：

```powershell
python -m py_compile bot.py trend_trader.py data_provider.py account_store.py config.py backtest.py tests\test_config.py
python -m unittest discover -s tests
```

## Discord 使用方式

在 bot 看得到的 Discord 頻道輸入：

```text
run
```

bot 會私訊你一則控制台面板。面板按鈕才是目前正式操作方式，其他舊文字指令不再使用。

面板會集中在同一則 Discord 訊息，按鈕列依序對應區塊：

```text
股票帳戶操作面板
策略只提供建議；實際成交請用面板同步。

控制台
策略
帳戶同步
帳戶設定
查詢

[控制台]
[產生策略]
[買進] [賣出] [同步持股]
[修改現金] [修改投入成本]
[帳戶總覽] [目前持股] [交易紀錄]
```

買進與賣出會先顯示確認頁，確認後才會真正修改帳戶並新增交易紀錄。買進股票必須在目前股票池中，不在股票池的代號會被拒絕。

如果伺服器頻道還看到舊的「股票帳戶操作面板」訊息，請手動刪除舊訊息。舊訊息上的按鈕可能會顯示「此交互失敗」，但新的 DM 面板可以正常使用。

## Google Cloud VM 部署

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

確認容器狀態：

```bash
docker compose ps
```

## 修改程式後重新部署

本機修改完後：

```powershell
cd C:\Users\bingyan\OneDrive\stock
python -m py_compile bot.py trend_trader.py data_provider.py account_store.py config.py backtest.py tests\test_config.py
python -m unittest discover -s tests
git status
git add .
git commit -m "Describe your change"
git push
```

到 VM 更新：

```bash
cd ~/stock
git pull
docker compose up -d --build
docker compose logs -f
```

只要 `docker compose ps` 顯示服務是 `Up`，bot 就會持續執行。`docker-compose.yml` 設定了 `restart: unless-stopped`，VM 重開或程式異常結束時 Docker 會自動重啟。

## 帳戶備份

帳戶資料在 VM：

```bash
~/stock/accounts
```

備份：

```bash
cd ~/stock
tar -czf accounts-backup-$(date +%Y%m%d).tar.gz accounts
```

## 注意事項

- 量化策略只供決策參考，不保證報酬。
- 實際成交價格通常和策略參考價格不同，所以買進、賣出、現金、成本都必須由 Discord 面板同步。
- `trend_trader.py` 不會替你建立實際買賣紀錄，但會更新既有持股的 `Peak_Price`。
- `DISCORD_WEBHOOK_URL` 不是目前主流程需要的環境變數；私訊面板不使用 webhook。
- FinMind 與 yfinance 都可能有延遲、缺漏或暫時失敗，正式交易前仍要自行確認券商資料。
