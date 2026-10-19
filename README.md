# 台股裸 K 波段研究室

手機／電腦網站：https://sy3dren-collab.github.io/taiwan-stock-screener/

沿用原有 Python 標準函式庫、SQLite 與 GitHub Pages 網站，研究持有約 5～20 個交易日的做多策略。**目前尚無通過驗證的策略，正式選股停用，沒有自動下單。85% 勝率尚未達成，也不是晉級門檻。**

舊四模型及一年結果保存在網站封存區、`archive/`、[舊規則](docs/strategies.md)與[舊 README](docs/legacy-readme.md)。不要用舊 CLI `python -m screener screen/update/backtest` 覆寫研究版首頁；這些入口僅保留相容性。

## 實際完成程度

已建立官方成交金額與來源證據儲存、三類裸 K 訊號、含成本與資金限制的日線回測、時序驗證、有限次數優化、晉級阻擋、研究版網站、備份及自動化。**真實五年比較與最終獨立測試尚未完成。** 詳見[交付報告](docs/delivery_report.md)、[原系統稽核](audit_report.md)、[資料來源及缺口](docs/data-sources.md)。

五年研究目標為 2021-06-19～2026-10-16；目前資料包含零散早期回補與原先 2025-06-19 起的 325 個交易日，不能把首尾跨度當作完整五年。舊資料缺實際成交金額及當日漲跌參考價，正在增量補抓；完整公司行動母表尚未接妥。即使 OHLCV 補齊，仍不會自動跨過公司行動檢查。最新精確缺口見網站 `data-quality.json`。

2025-10-17～2026-10-16 已被先前研究看過，記錄於 `docs/data-exposure.json`，不能重新宣稱為未見的封存樣本外。不能只把設定改為 pristine 消除污染。必須另行預先登記真正未見的未來期間，凍結規則後觀察；本版不偽造獨立一年績效。

## 安裝、測試與操作

Python 3.11+，建議 3.12；執行系統不需第三方 Python 套件、付費行情服務或 API 金鑰。

```bash
cd /workspace/taiwan-stock-screener
python3 -m unittest discover -s tests -v
# 真實官方日報驗證；指定已公布行情的交易日。
RUN_LIVE_TESTS=1 LIVE_DATE=2026-10-16 python3 -m unittest discover -s tests -p test_live.py -v

# 最新官方行情與唯一正式策略狀態。沒有合格正式策略即輸出空名單。
python3 -m screener.daily screen
python3 -m screener.quality audit
# 有限回補：每次最多30日期、60次HTTP嘗試、300秒，可重跑續接。
python3 -m screener.quality backfill
# 不連網重算；清楚標為離線，不假稱行情已更新。
python3 -m screener.daily screen --offline
# 資料不合格就停止，不產生假績效；每次最多9實驗／600秒。
python3 -m screener.optimizer research
# 現在因污染而阻擋，不會真的執行最終測試。
python3 -m screener.optimizer final-test
python3 -m screener.daily paper
python3 -m screener.backup save --directory .state/backup
# 還原會原子取代指定DB，請選正確目的地。
python3 -m screener.backup restore --directory .state/backup --db /tmp/restored-prices.sqlite3
python3 -m http.server 8000 --directory site
```

行情在 `.state/prices.sqlite3`；研究試驗在 `.state/experiments/`；正式策略僅能位於 `strategies/`，`strategy_registry.json` 預設 `active_strategy: null`。可用各命令的 `--help` 查看路徑選項。個別已核對公司行動可透過 `quality import-actions --events-file ...` 匯入，不代表市場事件全集完整，也不會自動通過資料門檻。

網頁測試需 Node.js、Playwright 1.56.1、Chromium；雲端目前已有。其他環境可在專案外安裝：

```bash
npm install --prefix /tmp/taiwan-browser-tests --no-package-lock playwright@1.56.1
/tmp/taiwan-browser-tests/node_modules/.bin/playwright install chromium
NODE_PATH=/tmp/taiwan-browser-tests/node_modules node tests/naked-browser.cjs
NODE_PATH=/tmp/taiwan-browser-tests/node_modules node tests/browser.cjs
```

測試的合成行情只存在測試案例，不會進入網站或正式資料庫。瀏覽器測試涵蓋 320／390／1280px、資料錯誤清空、紅漲綠跌 K 線、舊功能、無假曲線及手機無水平溢出。

## 三類候選與交易假設

完整可調參數在 `naked_k.json`，費用及資金在 `execution.json`。三類都只用當時已知的價位結構；成交金額僅做流動性篩選，不用 MA、RSI、ATR 進場。

| 候選 | 固定基準規則 |
| --- | --- |
| A 上升結構回調 | 最近90根內左右各2根確認轉折，最近兩高與兩低抬高；最近5根低點接近最新結構低點±2%，今日收盤突破前高且紅K、收盤位於本日區間上30% |
| B 盤整突破回測 | 排除最近15根後的固定60根區間，最高／最低−1≤25%；最近15根先收盤突破上緣0.5%，至少隔一根回測上緣±2%且不失守，再收盤確認；目標為區間高度投射 |
| C 多次支撐反轉 | 最近90根中末3個確認低點在中位支撐±2%、彼此至少隔5根；今日回測支撐、低點高於昨日、紅K突破前高，並站回支撐上0.5% |

共同條件：至少100根歷史；當時最近20個有效交易日**官方實際平均成交金額**≥5,000萬元、收盤≥20元、普通股；目標至少1.5R，收盤到結構停損風險≤8%。A/C目標用最近確認高點。停損為回測低點下0.5%。依接近支撐程度固定排序，最多10候選，不補足名額。

收盤後產生訊號，隔日有效開盤成交；無有效開盤／遇公司行動的舊價委託取消，不事後補選。開盤追價最多1%，重新檢查風報比。本金100萬、最多5部位、1000股整張、單筆初始風險最多本金1%、前20日已知均量1%參與率，資金不足跳過。佣金雙邊各0.1425%、最低20元、賣出稅0.3%、單邊滑價0.1%，有台股跳動單位。

結構停損／跳空不利開盤、同根同碰停損停利先停損；第20交易日開盤到期退出。達1.5R後以已確認低點更新隔日起生效的移動停損。5日是正常持有目標，不強迫持有，停損／目標可更早；停牌、跌停可能更晚。缺事件／持倉連續缺價或期末缺價會停止整次模擬，保留錯誤，不丟掉虧損交易。日線無法重建撮合佇列或部分成交；這些仍是模型假設。

訊號價採截至當時已生效、已公告的事件調整；交易用原始可成交價。已知分割調整股數及價位，現金股息列應收、支付前不可再投資；下市須官方清算價（可為有證據的0元），身份變更需映射，未知條件停止。上述引擎能力不代表真實事件資料已齊全。

## 驗證與優化

較早資料做378交易日訓練、63日驗證、步長63日；間隔20日Purging及5日Embargo，段尾停止進場讓20日持倉標籤結束；未結束持倉不得靜默歸零。各折重新以現金開始，平均驗證報酬不冒稱連續帳戶年報酬。

先 A/B/C 各跑一基準，再各做兩輪單條件修改；根據最早訓練段停損／到期特徵，只測支撐容許度縮10%或收盤位置提高0.05。失敗與中止均記錄，不無限循環。這是有限規則改善器，不是已證明能自動發現獲利策略的系統。

至少3折、合計60筆且每折10筆、正報酬及期望值、PF≥1.2、最大回撤≤15%、正報酬折比例≥67%、最大兩筆占正獲利≤50%；優於原基準及當時流動性前五普通股買入持有參考，另須2倍手續費／滑價、支撐參數±10%壓力測試通過。85%只是研究目標。固定多數範圍的市場階段分析及更豐富的成交敏感性仍待真實資料驗證。

研究程式最多提出一個凍結候選，不可改正式登錄。必須再通過真正未見的一次性最終測試及明確版本審核，才可用 `daily promote --approval-reference ...` 登錄；程式／成本／雜湊不同會拒絕。正式版本後續修改需重新研究審核，不被夜間候選覆蓋。紙上模型帳本與歷史回測分離，沒有真實委託。

## Actions、發布及持久化

- **Daily official data and Pages**：平日台北18:30、main程式推送或手動執行。只更新資料、固定唯一策略／停用狀態、紙上觀察與Pages；來源失敗發布明確錯誤並將工作流程標為失敗。
- **Bounded naked K research**：每日台北01:00有預算回補／研究，手動可選backfill、research、final-test。不能發布候選成正式策略，不直接部署Pages；下一次每日流程才帶出研究報告。
- **Validate research branch**：push／PR／手動跑Python、JS／shell與兩套Chromium測試。

Pages 使用 GitHub Actions 作為來源，本儲存庫已啟用。資料及實驗持久保存到獨立 **research-data** 分支；沒有時可只讀還原舊market-data。`.history`是CI專用第二份checkout，清理僅限該資料checkout，從不清理來源專案。所有修改通過測試才合併main；研究分支保留為檢視紀錄。

SQLite一致性快照壓縮為≤40MiB分片，有SHA-256與還原完整性檢查；分片先完成才原子換manifest。每次執行保存資料、實驗、前瞻帳本、最近報告，Actions診斷artifact保留7天。分支公開可下載；沒有私人憑證。

每日／研究共用concurrency鎖、單job25分鐘，抓取失敗有限重試，已完成日期可續接。排程可能延遲或被GitHub停用，請在[Actions](https://github.com/sy3dren-collab/taiwan-stock-screener/actions)檢查；失敗後可Run workflow補跑，不把舊日期當今日訊號。

實測60次請求／29日期約141秒；全期補抓需數十輪，最長每輪5分鐘，官方限流會更久。每晚研究上限10分鐘但資料不齊即快速停止。公開倉庫的GitHub-hosted標準runner通常不收執行費，實際帳戶政策／儲存額度未查核，不能保證免費；私有fork須另評估。每日提交大型SQLite仍使Git歷史持續增長，40MiB分片只處理單檔限制；長期應改分區／物件儲存與保留政策。

手機直接開上方網址，Safari分享或Chrome選單可加入主畫面，更新後重新整理即可，圖示不用重加。網站不建立離線行情快取。
