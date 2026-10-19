# 台股裸 K 波段研究室

手機／電腦網站：https://sy3dren-collab.github.io/taiwan-stock-screener/

沿用原有 Python 標準函式庫、SQLite 與 GitHub Pages 網站，研究持有約 5～20 個交易日的做多策略。**目前尚無通過驗證的策略，正式選股停用，沒有自動下單。85% 勝率尚未達成，也不是晉級門檻。**

網站封存區保留三個原策略的一年結果；RSI 回升已移除。完整舊四模型原始研究仍可由 `archive/` 與 Git 歷史追溯，[舊規則](docs/legacy-strategies.md)與[舊 README](docs/legacy-readme.md)。不要用舊 CLI `python -m screener screen/update/backtest` 覆寫研究版首頁；這些入口僅保留相容性。

## 一年研究回測與阻擋修復

依使用者要求優先檢驗 **2025-10-17～2026-10-16** 的單一合併策略，暖機自 **2025-04-01** 起。新的 `screener.annual` 將一年回溯研究與原有五年晉級驗證分開；五年完整性、一次性樣本外與正式啟用條件均保留。**一年已被前輪研究看過，結果只能稱回溯研究，不能稱獨立樣本外或用於晉級。**

修復項目包括優先回補所需期間、兩市場獨立限速及有限並行、截斷回應重試、官方除權息表介接、X／除息日開盤基準，以及理論除息調整價與跳動單位進位後基準的區分。純現金股利按官方數值入帳，付款日未知時不再投入。未支援事件或缺價只依當時已知資料中斷該股訊號暖機；持倉遇未知事件、連續缺價或期末無法結束仍讓整輪失敗，不事後丟棄交易。

```bash
# 每輪最多220日期、500次HTTP、1200秒；可重跑續接。
python3 -m screener.annual backfill
python3 -m screener.annual events
python3 -m screener.annual research
```

設定在 `annual_research.json`；規則仍用同一份 `naked_k.json` 與 `execution.json`。結果、全部交易、成本、淨值、月份績效、資料指紋與排除股票日統計在 `site/annual-backtest.json`，每次執行也加入回測帳本。首頁「新合併策略・一年回測」顯示實際結果，與正式策略績效分開。詳細資料政策見[一年研究說明](docs/annual-research.md)。

夜間排程優先續補一年資料並執行一年研究；手動工作可選 `annual-backfill`、`annual-research`，原有 `backfill`／`research`／`final-test` 保留為五年驗證入口。研究 job 上限45分鐘，抓取每主機最多每秒一次、最多三個日期同時處理。資料及一年報告也保存於 `research-data`，每日發布不會抹除它們。

## 實際完成程度

已建立官方成交金額與來源證據儲存、單一合併策略訊號、含成本與資金限制的日線回測、時序驗證、有限次數優化、晉級阻擋、研究版網站、備份及自動化。**真實五年回測與最終獨立測試尚未完成。** 詳見[交付報告](docs/delivery_report.md)、[原系統稽核](audit_report.md)、[資料來源及缺口](docs/data-sources.md)。

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
# 資料不合格就停止，不產生假績效；每次最多3實驗／600秒。
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

## 目前只研究一套合併策略

策略代號 **F**：「整理收復・趨勢回測・放量轉強」。來源為你的整理大量收復、趨勢回檔、帶量突破三個舊策略的可量化條件；RSI 已從程式執行入口、設定及網站比較移除。舊 A／B／C 研究也停止競爭，只保留回歸檢查及版本歷史。完整量化規則見 [單一策略](docs/strategy-single.md)。

流程為 **60根整理 → 1.5倍量收復或突破 → 確認高低點抬高 → 5根量縮回測支撐 → 1.2倍量轉強 → 隔日開盤**。兩種最初的區間事件共用後續確認、停損、排序與資金規則，不是多策略投票或任意取聯集。

至少100根歷史、當時20日官方平均成交金額≥5,000萬元、股價≥20元；回檔量比≤0.8，支撐容許距離2%，收盤距支撐≤4%，結構停損風險≤8%、目標至少1.5R。所有參數在 `naked_k.json`，成本在 `execution.json`。**85%僅長期目標，不作單一晉級或停止條件；不把合併視為已改善績效。**

收盤後產生訊號，隔日有效開盤成交；無有效開盤／遇公司行動的舊價委託取消，不事後補選。開盤追價最多1%，重新檢查風報比。本金100萬、最多5部位、1000股整張、單筆初始風險最多本金1%、前20日已知均量1%參與率，資金不足跳過。佣金雙邊各0.1425%、最低20元、賣出稅0.3%、單邊滑價0.1%，有台股跳動單位。

結構停損／跳空不利開盤、同根同碰停損停利先停損；第20交易日開盤到期退出。達1.5R後以已確認低點更新隔日起生效的移動停損。5日是正常持有目標，不強迫持有，停損／目標可更早；停牌、跌停可能更晚。缺事件／持倉連續缺價或期末缺價會停止整次模擬，保留錯誤，不丟掉虧損交易。日線無法重建撮合佇列或部分成交；這些仍是模型假設。

訊號價採截至當時已生效、已公告的事件調整；交易用原始可成交價。已知分割調整股數及價位，現金股息列應收、支付前不可再投資；下市須官方清算價（可為有證據的0元），身份變更需映射，未知條件停止。上述引擎能力不代表真實事件資料已齊全。

## 驗證與優化

較早資料做378交易日訓練、63日驗證、步長63日；間隔20日Purging及5日Embargo，段尾停止進場讓20日持倉標籤結束；未結束持倉不得靜默歸零。各折重新以現金開始，平均驗證報酬不冒稱連續帳戶年報酬。

只跑 F 基準，再做兩輪單條件修改；根據最早訓練段停損／到期特徵，只測支撐容許度縮10%或收盤位置提高0.05。失敗與中止均記錄，不無限循環。這是有限規則改善器，不是已證明能自動發現獲利策略的系統。

至少3折、合計60筆且每折10筆、正報酬及期望值、PF≥1.2、最大回撤≤15%、正報酬折比例≥67%、最大兩筆占正獲利≤50%；優於原基準及當時流動性前五普通股買入持有參考，另須2倍手續費／滑價、支撐參數±10%壓力測試通過。85%只是研究目標。固定多數範圍的市場階段分析及更豐富的成交敏感性仍待真實資料驗證。

研究程式最多提出一個凍結候選，不可改正式登錄。必須再通過真正未見的一次性最終測試及明確版本審核，才可用 `daily promote --approval-reference ...` 登錄；程式／成本／雜湊不同會拒絕。正式版本後續修改需重新研究審核，不被夜間候選覆蓋。紙上模型帳本與歷史回測分離，沒有真實委託。

## Actions、發布及持久化

- **Daily official data and Pages**：平日台北18:30、main程式推送或手動執行。只更新資料、固定唯一策略／停用狀態、紙上觀察與Pages；來源失敗發布明確錯誤並將工作流程標為失敗。
- **Single fusion strategy research**：每日台北01:00優先續補一年資料並研究，手動可選annual-backfill、annual-research及原五年驗證入口backfill、research、final-test。每次執行保存結果及Actions摘要，再自動發布研究報告到Pages；不會啟用未驗證候選。
- **Validate research branch**：push／PR／手動跑Python、JS／shell與兩套Chromium測試。

Pages 使用 GitHub Actions 作為來源，本儲存庫已啟用。資料及實驗持久保存到獨立 **research-data** 分支；沒有時可只讀還原舊market-data。`.history`是CI專用第二份checkout，清理僅限該資料checkout，從不清理來源專案。所有修改通過測試才合併main；研究分支保留為檢視紀錄。

SQLite一致性快照壓縮為≤40MiB分片，有SHA-256與還原完整性檢查；分片先完成才原子換manifest。每次執行保存資料、實驗、前瞻帳本、所有回測紀錄與最近報告，Actions診斷artifact保留7天。分支公開可下載；沒有私人憑證。

每日／研究共用concurrency鎖、每日job25分鐘、研究job45分鐘，抓取失敗有限重試，已完成日期可續接。排程可能延遲或被GitHub停用，請在[Actions](https://github.com/sy3dren-collab/taiwan-stock-screener/actions)檢查；失敗後可Run workflow補跑，不把舊日期當今日訊號。

實測60次請求／29日期約141秒；全期補抓需數十輪，最長每輪5分鐘，官方限流會更久。每晚研究上限10分鐘但資料不齊即快速停止。公開倉庫的GitHub-hosted標準runner通常不收執行費，實際帳戶政策／儲存額度未查核，不能保證免費；私有fork須另評估。每日提交大型SQLite仍使Git歷史持續增長，40MiB分片只處理單檔限制；長期應改分區／物件儲存與保留政策。

手機直接開上方網址，Safari分享或Chrome選單可加入主畫面，更新後重新整理即可，圖示不用重加。網站不建立離線行情快取。

## 每次回測如何查看

每次 `python -m screener.optimizer research` 或 `final-test`（包含資料不足／失敗）都有獨立 run_id、程式／資料指紋、原因、勝率、交易筆數、平均驗證淨報酬、最大單折回撤、PF、期望值及保留／淘汰狀態。各折現金重啟，跨折平均報酬不稱為帳戶年報酬。沒有有效回測的數值顯示「—」，不是0%。

手機網站「每次回測結果」可展開最近紀錄、下載完整報告；摘要在 `site/research-history.json`、`site/latest-backtest.md`，最近20次完整JSON供下載，索引最多200次。完整帳本與全部快照保存於research-data分支的 `runs/`，每輪實驗完整資料仍在 `experiments/`。長期儲存成長與既有SQLite一樣需管理。

GitHub每次研究的Actions頁面會顯示本次報告，並自動重新部署研究頁。聊天視窗沒有背景主動推播能力；這裡可回報本次實際結果，之後的自動結果請從網站或Actions查看。資料不足也會留下紀錄，不會靜默跳過。研究程式錯誤仍輸出錯誤報告，保存後發布，再將工作流程標記失敗。
