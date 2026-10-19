# 台股波段觀察室

正式網站（手機／電腦）：**https://sy3dren-collab.github.io/taiwan-stock-screener/**

使用臺灣證券交易所、證券櫃檯買賣中心的公開收盤行情，建立 **1～4 週波段交易研究候選名單**。Python 標準函式庫完成資料取得、SQLite 儲存與量化篩選；原生 HTML/CSS/JavaScript 網站以 GitHub Pages 發布。沒有下單功能。手機版的資料流程與維護分工見 [系統架構](docs/architecture.md)。

## 目前狀態與驗證範圍

第一版包含資料介接、歷史儲存、增量更新、策略、響應式繁體中文網站與自動發布工作流程。已成功從官方回補 **2025-06-19～2026-10-16**，共 **325 個有行情交易日、623,320 筆 OHLCV**；SQLite 完整性檢查通過。正式網站結果是截至 2026-10-16 的官方行情快照，不是即時報價。

截至該日共 1,942 檔股票有有效行情，1,927 檔歷史足夠，預設策略有 **1 檔**符合全部條件。候選少於五檔時明確提示，不會放寬條件或加入模擬行情。測試用價格只存在 tests 的合成 fixture，不會寫入正式網站或正式歷史資料。

上市與上櫃兩項正式 API 整合測試、離線解析／策略／儲存／失敗處理測試、Chromium 桌機／手機測試皆已執行通過。程式與官方歷史資料已分別推送至 main 與 market-data。GitHub Pages 已啟用，[正式工作流程紀錄](https://github.com/sy3dren-collab/taiwan-stock-screener/actions/workflows/daily.yml)可檢查每次官方資料更新、歷史保存及網站部署的最新狀態。正式首頁、行情 JSON、JavaScript、CSS、網站圖示與 manifest 均確認 HTTP 200，部署資產與儲存庫相符。

## 本機操作

需要 Python 3.11+（建議 3.12，環境已驗證 3.12.14），不需第三方 Python 套件、API 金鑰或資料庫服務。

```bash
cd /workspace/taiwan-stock-screener
python3 -m unittest discover -s tests -v

# 首次抓取約 180 個日曆日，取得至少 MA60 所需歷史。
# 首次約 250 次官方請求；一年研究另需下方 --ensure-start 回補暖機。失敗會停止並保留已完成日期。
python3 -m screener update

# 後續相同指令僅補缺漏日期，並重抓最近 7 個日曆日（修正／延遲行情）。
python3 -m screener update

# 以指定截止日產生訊號，不使用其後行情；非交易日顯示最近交易日並提示。
python3 -m screener update --end 2026-10-16

# 明確擴充更早的歷史範圍，仍從官方逐日抓取。
python3 -m screener update --start 2026-01-01 --end 2026-10-16

# 不連網，用既有資料重新選股（結果標示為離線重算）。
python3 -m screener screen

# 本機靜態服務；瀏覽器開啟伺服器印出的本機位址。
python3 -m http.server 8000 --directory site
```

預設資料庫：`.state/prices.sqlite3`，結果：`site/results.json`。可使用 `--db`、`--output`、`--config` 指定位置。`--lookback-days`（至少 100，預設 180）只決定空資料庫的首次回補範圍；要擴大已有歷史，使用 `--start`。`--delay` 控制請求間隔（至少 1 秒，預設 2 秒），失敗最多嘗試 3 次，保留 TLS 驗證。

截至日以 Asia/Taipei 計算：18:00 後使用當日，其前使用前一日。不下載未來日期。週末不請求；平日是否交易依官方報表的明確無資料回應判斷，未知格式或錯誤不當作休市。資料落後截止日超過 7 天會報錯，長假時需人工核對官方公告。

### 真實資料連線驗證（部署前必要）

在可連到官方網域的環境，選擇**已公布資料的實際交易日**：

```bash
RUN_LIVE_TESTS=1 LIVE_DATE=2026-10-16 python3 -m unittest discover -s tests -p test_live.py -v
python3 -m screener update
```

兩個市場都應成功取得超過 100 檔真實 OHLCV，再檢查更新結果的 `status` 為 `ok`、`as_of` 日期正確、`sufficient_history_count` 合理。沒有候選不代表故障，可能沒有股票符合條件；歷史不足會另外提示。

HTTPS 網域 `www.twse.com.tw`、`www.tpex.org.tw`、`api.github.com`、`sy3dren-collab.github.io` 目前均可連線，四個必要網域也已保存至環境設定草稿。草稿保存本身不代表新環境已發布；後續環境仍應保留這些網域。GitHub Actions 的 GitHub-hosted runner 不使用這份雲端網路設定，但仍可能遇到官方限流／阻擋。本儲存庫的 Pages 已由管理者啟用；若 fork 到其他儲存庫，仍須由該儲存庫管理者選擇 GitHub Actions 作為 Pages 來源。

### 網頁測試（選用開發工具）

網頁執行本身不需要 Node.js。自動瀏覽器測試需要 Node.js、Playwright 與 Chromium；目前雲端已提供這些工具，可執行：

```bash
node --check site/app.js
node tests/browser.cjs
```

其他開發機可將測試工具安裝在儲存庫以外，避免引入網站執行相依：

```bash
npm install --prefix /tmp/taiwan-browser-tests --no-package-lock playwright@1.56.1
node /tmp/taiwan-browser-tests/node_modules/playwright/cli.js install chromium
NODE_PATH=/tmp/taiwan-browser-tests/node_modules node tests/browser.cjs
```

若 Chromium 位於特殊路徑，可設定 `CHROMIUM_PATH`。測試會暫時在 127.0.0.1:8765 啟動 HTTP 服務並自行關閉，以攔截結果請求的方式測試合成資料；正式 site/results.json 不受影響。截圖輸出至 `/tmp/taiwan-stock-desktop.png`、`/tmp/taiwan-stock-mobile.png`。

## 官方資料與歷史儲存

- 上市：`https://www.twse.com.tw/exchangeReport/MI_INDEX?date=YYYYMMDD&type=ALLBUT0999&response=json`
- 上櫃：`https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date=YYYY/MM/DD&response=json`
- 普通股範圍：四位數字且首碼非 0，上市另排除 91xx 存託憑證。不包含 ETF、權證、特別股等其他代號格式；不是所有交易商品。
- 儲存每日開、高、低、收、成交**股數**與名稱、代號、市場；遇到「仟股」欄位轉換為股。不用成交金額或張數代替成交量。
- 依欄位名稱定位 OHLCV，支援 TWSE 舊 fieldsN/dataN 及新版 tables，拒絕日期錯誤、重複代號、不合法價量、未知 schema、HTTP／JSON 錯誤。停牌／無 OHLC 證券不建立 bar。
- `(market, code, date)` 為 SQLite 主鍵。單日上市與上櫃皆取得並驗證後，才以單一交易取代該日資料並記錄 sessions。兩市場交易日狀態不一致會失敗，不會部分覆蓋該日。
- 任一日失敗即停止，不會標記失敗日期完成；先前完成日期保留。重試從最近完成日期前 7 天開始。`--start` 可重抓更早資料；超過七天才公布的官方修正不會自動發現。
- 執行失敗寫出 `status: error`、具體原因、空候選，並回傳非零結束碼。網站不以舊候選或模擬行情冒充本日結果。
- 每日結果是收盤後快照，不是即時行情；網站顯示行情日期、產生時間、更新警示，距今超過 4 天另顯示資料可能過期。

## 原策略定義與調整

此節是原策略 `trend_pullback`。你的「整理區間＋大量收復／近似頭肩底」已獨立為 `user_range_reclaim`；另有帶量突破及 RSI 回升兩個比較模型。完整規則、量化門檻與成交假設見 [獨立策略與初步回測](docs/strategies.md)。

`strategy.json` 設定原策略與共同風險／流動性門檻；`models.json` 設定型態、量能及比較模型；`execution.json` 設定持有、資金及費用。調整後重跑 `update` 與 `python3 -m screener.backtest`。下列原策略條件為 AND：

| 條件 | 精確規則與預設 |
| --- | --- |
| 上升趨勢 | 收盤 > MA20 > MA60；MA20／5 個交易日前的 MA20 − 1 > 0 |
| 高低點抬高 | 最近 60 根 K 線中，最近兩個確認高點依序升高，最近兩個確認低點依序升高；轉折高／低必須嚴格大於／小於左右各 2 根的高／低，右側未滿 2 根不算確認 |
| 回檔幅度 | 1 − 前 5 日最低價／前 20 日最高價 ≥ 2%（兩者皆排除當日） |
| 接近支撐 | 支撐候選為 MA20、最近確認波段低點；支撐 ≤ 收盤，收盤／支撐 − 1 ≤ 4%，且 abs（前 5 日最低價／支撐 − 1）≤ 4%；兩者合格取最靠近收盤者 |
| 量縮 | 排除當日，前 5 日均量／再此前 20 日均量 ≤ 0.8 |
| 轉強 | 當日收盤 > 前日最高價、當日開盤及前日收盤 |
| 流動性 | 含當日最近 20 日平均成交量 ≥ 300,000 股 |
| 停損 | min（支撐、前 5 日最低價）− 0.5 × ATR14；ATR 為真實區間的簡單平均，非 Wilder 平滑 |
| 參考目標 | 最近確認波段高點，不以任意倍數捏造目標 |
| 風險門檻 | 停損 > 0；（收盤 − 停損）／收盤 ≤ 10%；（目標 − 收盤）／（收盤 − 停損）≥ 1.5 |
| 異常跳動 | 最近 60 根之相鄰收盤變化絕對值 > 15% 時排除（原始價、未還原權息；此條件不能識別所有公司行動） |
| 數量 | 目標至少 5 檔、最多 10 檔；不足不補，超過依分數取前 10，分數相同依市場、代號排序 |

分數＝40 ×（1 − 支撐距離／距離上限）＋30 ×（1 − 量縮比）＋20 × min（風報比／3, 1）＋10 × min（均線升幅／5%, 1）。分數只是透明的相對排序，不是勝率。策略沒有經回測證明可獲利，1～4 週是研究持有目標。初步回測已明訂收盤觸發後次日開盤進出、停利最少觀察 5 日及第 20 日時間出場；不是報酬保證。

沒有當日行情或少於所需歷史根數（預設 65 根）的股票不參與判斷。圖表呈現最近最多 60 根原始 K 線與成交量，紅漲綠跌，灰色為開收相同。滑鼠停在 K 線可查看日期與 OHLCV；另列支撐、停損、參考目標及風險報酬比。

## GitHub Actions 與 Pages 部署

1. 將這份程式碼推送至 GitHub 儲存庫的 `main`（本地提交不等於已推送）。
2. 在 **Settings → Pages → Build and deployment → Source** 選擇 **GitHub Actions**。
3. 確認 Actions 已啟用，允許工作流程寫入儲存庫及部署 Pages。工作流程宣告 `contents: write`、`pages: write`、`id-token: write`；組織政策／分支規則也必須允許機器帳號建立及更新 `market-data`，該分支不應啟用禁止此機器帳號直接推送的規則。
4. 至 **Actions → Daily official data and Pages → Run workflow**，使用 `main`，首次保持 `lookback_days=180`；研究流程另自動確保一年＋120 日暖機，首次可能需數十分鐘。後續只補缺漏日期並重查最近行情。
5. 查看 Actions summary、錯誤紀錄與 Pages deployment。成功時網站網址由 GitHub Pages 提供，專案網站通常為 `https://<帳號>.github.io/taiwan-stock-screener/`。

發布後，在手機開啟正式 Pages 網址，透過瀏覽器的分享／選單選擇「加入主畫面」即可快速開啟；手機不需安裝 Python。本站不提供離線行情快取，避免把舊價格當作新行情。

工作流程在週一～週五台北時間 **18:30**（UTC 10:30）執行；休市依官方回應處理。GitHub 排程可能延遲，也不保證準時；公開儲存庫長期無活動可能停用排程，請定期檢查。修改程式碼／策略推送到 main 也會更新，README／docs 單獨變更不會觸發。

### 歷史持久化與錯誤發布

- 第二份隔離 checkout `.state` 專用於 `market-data` 分支：保存壓縮的 `prices.sqlite3.gz`（還原後為 SQLite）、`latest-results.json` 與 `latest-backtest.json`。首次沒有分支時，僅清空這份 CI 專用 checkout 的來源檔案以建立獨立資料分支；不動原始 main checkout。
- 每次從資料分支恢復，不依賴易被驅逐的 Actions cache。即使更新中途失敗，也保存已完成的原子日期與錯誤結果，便於繼續回補。SQLite 是二進位檔，長期每天提交會增加 Git 大小；規模擴大時應改用物件儲存／分區檔及保留政策。
- 完成更新後以 Pages artifact 發布 `site/`，資料庫不包含在 Pages artifact。請注意：若儲存庫公開，`market-data` 分支中的公開來源歷史與診斷 JSON 仍可被下載。
- 官方更新失敗時仍嘗試發布明確的錯誤頁，發布後工作流程標記失敗；不悄悄繼續顯示舊候選。若 GitHub 推送／Pages 本身失敗，舊頁面可能仍在，需查看其資料日期與 Actions 紀錄。
- 排程有 concurrency 鎖，避免資料分支及 Pages 同時被多個執行覆蓋。不會將網站結果寫回 main，也不會形成每日提交觸發循環。
- 不需要個人存取權杖；GitHub 自動提供的 `GITHUB_TOKEN` 用於資料分支與 Pages。若失敗，不要在程式碼或聊天中貼金鑰。

## 測試與專案結構

```text
screener/data.py        官方報表解析、下載、SQLite
screener/strategy.py    量化參數、波段結構、評分與選股
screener/interfaces.py 歷史資料 Protocol 與指定日期訊號入口
screener/__main__.py    更新／離線選股 CLI、錯誤 JSON
refinements.json       每個模型一組固定改良規則與風控
screener/research.py    滾動一年、日期覆蓋、前八後四分段與診斷
screener/refinements.py 獨立改良候選
strategy.json          原策略與共同風險／流動性參數
models.json            你的獨立型態策略及比較模型參數
execution.json         交易成本、資金與 5～20 日持有規則
screener/backtest.py    四模型初步歷史模擬
screener/models.py      獨立策略與量化型態
screener/execution.py   模型成交價、跳動單位與進場計畫
site/                  靜態網站與結果 JSON
tests/                離線單元、端到端管線、選用真實 API、Chromium UI 測試
.github/workflows/     每日更新、資料分支持久化與 Pages 發布
```

離線測試涵蓋兩市場解析與單位換算、日期與價量檢查、資料更正、增量範圍、失敗日不落庫、正向與反向策略案例、預設策略可選出候選、不足不湊數、最多十檔、未來資料隔離、錯誤輸出。真實 API 測試預設跳過，需依上方命令明確啟用。瀏覽器測試另驗證手機無水平溢出、K 線紅漲綠跌、搜尋／排序／市場過濾、參數表、資料來源失敗狀態及股票名稱不被當作 HTML 執行。

## 初步回測與限制

已加入四模型獨立回測及各一個固定改良候選，預設比較最近一個日曆年（另備暖機），輸出 `site/backtest.json`：共同期間與前八後四分段的估算報酬、含成本勝率、每日淨值回撤、每筆模型進出場日期與價格、未平倉部位、費稅與出場原因診斷。候選規則及風控先固定、不搜尋最佳參數，保留原版及不利結果，不自動替換每日選股。網站可切換四組候選，並查看各策略的交易紀錄。你的方法單獨標示，兩種型態均強制要求收復／突破當天大量，不混入其他模型條件。

```bash
python3 -m screener update --ensure-start 2025-06-19 --end 2026-10-16
python3 -m screener.backtest
python3 -m screener.backtest --start 2025-10-17 --end 2026-10-16
python3 -m screener screen --model user_range_reclaim
```

這是**原始未還原權息的初步模擬**：尚未計入股息、完整公司行動、開盤撮合佇列及下市處理，未完成多年度與獨立樣本外驗證。期末估算報酬含未平倉，勝率只計已平倉；不足 30 筆會提示樣本少。規則、費用、暖機、部位上限與限制均揭露於 [策略文件](docs/strategies.md)，不把初步結果稱為策略已通過績效驗證。

`HistoricalFeed.histories(as_of)`、`screen_as_of` 及 `screen_model` 保留指定日期訊號介面；`simulate` 逐日切斷未來資料、以前日收盤預定隔日名單。GitHub Actions 每日更新後比較四模型、保存回測 JSON 並發布結果，失敗時輸出錯誤並標記工作流程失敗。
