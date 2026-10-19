# 官方來源、調整與尚缺資料

2026-10-19實際連線調查；TLS與憑證驗證均保留。

| 來源 | 已驗證欄位／用途 | 限制 |
| --- | --- | --- |
| TWSE `exchangeReport/MI_INDEX?date=YYYYMMDD&type=ALLBUT0999&response=json` | 日開高低收、成交股數、成交金額、當日帶符號漲跌價差 | 當日參考價以本日收盤減帶符號價差；權息特殊標記不可猜測 |
| TPEx `www/zh-tw/afterTrading/dailyQuotes?date=YYYY/MM/DD&response=json` | 同上；欄位標示仟股／仟元時才換算 | 絕不把「次日參考價」當成當日可用參考 |
| [TWSE除權息計算表](https://www.twse.com.tw/rwd/zh/exRight/TWT49U?response=json&startDate=20250101&endDate=20261016) | 本次返回2,707筆，日期、前收、權息參考價、權息類別、權值＋息值 | 2025-01-01～2026-10-16查詢包含非普通股；「權值＋息值」不能直接當現金股息，表中季報資訊可能是今日更新，不可倒灌歷史 |
| [TPEx除權息計算表](https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate=2025/01/01&endDate=2026/10/16&response=json) | 本次返回2,424筆且totalCount一致，含現金股利、配股及增資欄位 | 尚須公告／付款時點、拆併股及版本核對；單日date查詢可能顯示次日事件，不可把發布日當生效日 |
| [TWSE終止上市](https://www.twse.com.tw/rwd/zh/company/suspendListing?response=json) | 本次265筆日期、名稱、代號 | 沒有完整清算價、支付條件、繼受公司映射；不可沿用末價或刪掉損失 |

上述三份事件原始JSON、來源URL、SHA-256、觀測時間保存在資料庫`corporate_source_evidence`，供後續正式介接稽核；**目前未將它們冒稱完整公司行動母表**。TPEx終止交易／身份變更、兩市場完整分割／減資及支付條件仍未完成接入，`lifecycle_coverage`不會因抓到少數事件就自動通過。

`bars`保存原始價、實際股數與實際成交金額；NULL就是缺少，不能以收盤×量回填。主鍵防重；單日兩市場全部驗證才原子存入。`sessions`保留實際交易／官方休市回應，工作日沒回應不自動當休市。`source_batches`保存每份日報來源、內容雜湊、抓取時間；舊缺證據須補抓。

歷史普通股以當日官方日報代碼形式篩選（四碼、首碼非0，TWSE排除91xx存託憑證），不套用今天的存續名單。但尚欠完整歷史證券類別／身份母表，不能宣稱存活者偏差及所有特殊證券已完全排除。

調整訊號歷史只使用當時已公告且已生效事件；原始價格不被覆寫。完整交易引擎可處理已提供條件的分割、股息應收、身份轉換及有證據清算，並拒絕未知條件。缺事件時停止有效研究，而不是讓不可信結果參賽。行情缺漏可由排程自動續接；公司行動資料契約與來源整合仍需開發，單靠重跑不會消失。
