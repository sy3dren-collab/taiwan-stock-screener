# 台指期當沖情報站：部署與費用界線

頁面 `site/premarket.html` 與股票選股、回測分開。首頁提供入口。以台指期公開日／夜盤報表、美股四大指數、台積電ADR、美元新台幣、利率、VIX及相關新聞為主，另外提供官方FOMC、CPI、非農、PCE日程連結。不憑空產生經濟事件時間、消息摘要、買賣訊號或預測。

## 費用與必要帳號

即時按鈕採 Cloudflare Workers **Free**。查核來源為Cloudflare官方文件及其官方GitHub文件庫：

- https://developers.cloudflare.com/workers/platform/pricing/
- https://developers.cloudflare.com/workers/platform/limits/
- https://github.com/cloudflare/cloudflare-docs/blob/production/src/content/docs/workers/platform/pricing.mdx
- https://github.com/cloudflare/cloudflare-docs/blob/production/src/content/docs/workers/platform/limits.mdx

2026-10-27查閱的文件記載免費每日100,000請求、每次10ms CPU；超出每日額度回傳1027，並非免費方案自動按量扣款。付費Workers方案最低每月US$5，另有用量計費，**本專案沒有授權開通、升級、綁定付費儲存或任何自動付費方案**。來源限制或免費CPU不足時應先顯示失敗並說明，不能默默升級。真正部署仍須確認帳號當時條款、Free方案狀態及實測CPU，不能用本機測試宣稱已符合雲端額度。Yahoo及RSS是公開來源，沒有訂閱交易所逐筆行情或任何付費新聞API。

目前沒有可用的Cloudflare登入／部署憑證，因此尚不能替使用者部署或驗證公開後端。不得將此狀態描述為即時服務已上線。`premarket-config.json` 預設 `api_base_url:null`，即時按鈕停用並說明原因；靜態資料與來源錯誤仍可查看。

## 最少人工連接步驟

1. 使用者自行登入／建立Cloudflare帳號，確認Workers Free，不升級付費、不提供付款授權。勿將密碼、API token貼到聊天或網站。
2. 在本機已登入Cloudflare的環境執行 `npx wrangler deploy --config backend/wrangler.jsonc`；或在Cloudflare Workers的GitHub匯入功能連接此儲存庫，部署指令使用相同命令。若介面要求付款，先停止並確認，不能按同意。
3. 將部署完成的公開 `https://…workers.dev` 網址設為儲存庫變數 `MARKET_BRIEF_API`。這只是公開網址，不是密鑰；也可提供公開網址讓維護者設定。
4. 執行網站發布工作。瀏覽器只呼叫此網址的 `/api/brief`，不用GitHub登入、不含部署憑證。
5. 實測按鈕、CORS、來源成功／部分失敗、快取提示、報價日期、期貨合約與日夜盤標籤、手機排版及Workers用量。未測通前不能宣稱服務啟用完成。

CLI需要驗證的Cloudflare帳號由使用者自己登入；本環境沒有帳號連接工具，不能代替使用者建立帳號或接受條款。

## 更新與資料語義

`backend/worker.mjs` 僅允許設定的Pages Origin，僅接受固定來源、固定API路徑的唯讀GET，沒有任意URL代理。CORS不是使用者身分驗證；這是公開低用量資料API。120秒內共用快取，畫面明示命中快取而非假稱重新抓取。來源有時間、原始連結及SHA256，前端不持有秘密。免費用量有每日硬上限，仍可能被濫用而暫停，不能保證可用性。

Yahoo報價採 `regularMarketTime`／`regularMarketPrice`，與最近一個更早交易日收盤比較；可能延遲，並非台指期即時行情。`^TNX` 為殖利率指標，`TWD=X` 為新台幣／美元；VIX上升不等於股市上漲。期交所資料為 `DailyMarketReportFut`，只列TX月合約，保留報表交易日及原始交易時段，不猜測其對應的夜盤日曆日期。這份交易報表不會變成即時價；遇不符格式、沒有資料或來源錯誤便明示缺漏，並保留官方即時行情網站入口。

新聞只呈現原始RSS標題、來源媒體、發布時間與原文連結。後端以半導體／權值股、央行／數據、地緣／政策、股匯市等關鍵字作相關性標籤，排序不是利多利空判斷，關鍵字也可能漏掉重要事件。只保留48小時內新聞，RSS不代表完整歷史庫。

`python -m screener.premarket --mode latest` 為GitHub來源收集備援；`--mode premarket` 截至台北08:20並僅使用已結束時段。排程週一到週五08:10，Actions可能排隊或延遲。GitHub備援不是一按即時後端，需如實區分。

本地受限網路已補存來源網域草稿，草稿儲存不等於執行環境已套用。網路未開放時只記錄真實失敗，不以測試資料發布。測試fixture只存在測試攔截或記憶體中。
