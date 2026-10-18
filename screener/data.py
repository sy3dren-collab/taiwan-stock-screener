"""Official daily market reports. Never substitute generated market prices."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import math
import re
import sqlite3
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class DataError(RuntimeError):
    """The official report could not be obtained or validated."""


@dataclass(frozen=True)
class Bar:
    market: str
    code: str
    name: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int  # shares, never lots


URLS = {
    "TWSE": "https://www.twse.com.tw/exchangeReport/MI_INDEX",
    "TPEX": "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes",
}
ALIASES = {
    "code": ("證券代號", "代號", "股票代號"),
    "name": ("證券名稱", "名稱", "股票名稱"),
    "open": ("開盤價", "開盤"),
    "high": ("最高價", "最高"),
    "low": ("最低價", "最低"),
    "close": ("收盤價", "收盤"),
    "volume": ("成交股數", "成交仟股", "成交千股"),
}


def normalize(value: object) -> str:
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", str(value)))


def report_date(value: object) -> str:
    s = str(value).strip()
    if re.fullmatch(r"\d{8}", s):
        return date(int(s[:4]), int(s[4:6]), int(s[6:])).isoformat()
    parts = re.findall(r"\d+", s)
    if len(parts) == 3:
        y, m, d = map(int, parts)
        return date(y + 1911 if y < 1911 else y, m, d).isoformat()
    raise DataError(f"無法辨識官方資料日期：{s!r}")


def number(value: object) -> float:
    try:
        result = Decimal(normalize(value).replace(",", ""))
        if not result.is_finite():
            raise InvalidOperation
        value = float(result)
        if not math.isfinite(value):
            raise InvalidOperation
        return value
    except (InvalidOperation, ValueError):
        raise DataError(f"無效行情數值：{value!r}") from None


def parse_report(market: str, day: date, payload: object) -> list[Bar]:
    if market not in URLS or not isinstance(payload, dict):
        raise DataError("官方回應格式不正確")
    status = str(payload.get("stat", ""))
    # Only documented no-data messages mean no session; HTTP errors never do.
    if status and status.lower() != "ok":
        if "沒有符合條件的資料" in status or "查無資料" in status:
            return []
        raise DataError(f"{market} 官方回應：{status}")
    for key in ("date", "reportDate"):
        if payload.get(key) and report_date(payload[key]) != day.isoformat():
            raise DataError(f"{market} 回應日期與請求日期不符")
    tables = list(payload.get("tables", []))
    # Older TWSE reports use fields9/data9 (the index changes over time).
    for key, fields in payload.items():
        if key.startswith("fields"):
            tables.append({"fields": fields, "data": payload.get("data" + key[6:])})
    for table in tables:
        if not isinstance(table, dict) or not isinstance(table.get("fields"), list):
            continue
        headers = [normalize(f) for f in table["fields"]]
        columns = {}
        for field, aliases in ALIASES.items():
            indices = [i for i, h in enumerate(headers) if h in aliases]
            if indices:
                columns[field] = indices[0]
        if len(columns) != len(ALIASES):
            continue
        rows = table.get("data")
        if not isinstance(rows, list):
            raise DataError(f"{market} 行情表缺少資料列")
        bars = []
        seen = set()
        for row in rows:
            if not isinstance(row, list) or len(row) <= max(columns.values()):
                raise DataError(f"{market} 行情欄位不完整")
            code = normalize(row[columns["code"]])
            # Four-digit ordinary shares; exclude listed depositary receipts (91xx).
            if not re.fullmatch(r"[1-9]\d{3}", code) or (market == "TWSE" and code.startswith("91")):
                continue
            raw = {k: row[i] for k, i in columns.items()}
            missing = {"--", "---", "----", "-", "", "除權", "除息"}
            if all(normalize(raw[k]) in missing for k in ("open", "high", "low", "close")):
                # Suspended/untraded securities do not have a usable OHLC bar.
                continue
            prices = {k: number(raw[k]) for k in ("open", "high", "low", "close")}
            volume = number(raw["volume"])
            if headers[columns["volume"]] in ("成交仟股", "成交千股"):
                volume *= 1000
            if volume < 0 or not volume.is_integer() or min(prices.values()) <= 0:
                raise DataError(f"{market} {code} 價量不合法")
            if not (prices["low"] <= min(prices["open"], prices["close"]) <= max(prices["open"], prices["close"]) <= prices["high"]):
                raise DataError(f"{market} {code} OHLC 範圍不合法")
            if code in seen:
                raise DataError(f"{market} {code} 出現重複資料")
            seen.add(code)
            bars.append(Bar(market, code, str(raw["name"]).strip(), day.isoformat(), **prices, volume=int(volume)))
        if rows and not bars:
            raise DataError(f"{market} 行情表沒有可辨識的普通股資料")
        return bars
    raise DataError(f"{market} 找不到官方 OHLCV 行情欄位（可能是資料格式變更或網站阻擋）")


class OfficialClient:
    def __init__(self, delay: float = 2.0, retries: int = 3):
        self.delay, self.retries = delay, retries
        self.last_request = 0.0

    def daily(self, market: str, day: date) -> list[Bar]:
        params = ({"date": day.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"}
                  if market == "TWSE" else {"date": day.strftime("%Y/%m/%d"), "response": "json"})
        url = URLS[market] + "?" + urlencode(params)
        last = None
        for attempt in range(self.retries):
            time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                request = Request(url, headers={"User-Agent": "TaiwanStockScreener/0.1 (public daily report research)", "Accept": "application/json"})
                with urlopen(request, timeout=40) as response:
                    payload = json.loads(response.read().decode("utf-8-sig"))
                return parse_report(market, day, payload)
            except Exception as exc:
                last = exc
                if attempt + 1 < self.retries:
                    time.sleep(2 ** attempt)
        raise DataError(f"{market} {day.isoformat()} 官方資料取得失敗：{last}") from last


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS bars (
          market TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
          date TEXT NOT NULL, open REAL NOT NULL, high REAL NOT NULL,
          low REAL NOT NULL, close REAL NOT NULL, volume INTEGER NOT NULL,
          PRIMARY KEY(market, code, date));
        CREATE INDEX IF NOT EXISTS bars_date ON bars(date);
        CREATE TABLE IF NOT EXISTS sessions (
          date TEXT PRIMARY KEY, twse_count INTEGER NOT NULL, tpex_count INTEGER NOT NULL);
        """)

    def save_day(self, day: date, reports: dict[str, list[Bar]]) -> None:
        if set(reports) != set(URLS):
            raise DataError("上市與上櫃資料必須一起成功才能儲存")
        if bool(reports["TWSE"]) != bool(reports["TPEX"]):
            raise DataError(f"{day} 兩市場交易日狀態不一致，拒絕部分更新")
        if any(b.market != market or b.date != day.isoformat() for market, bars in reports.items() for b in bars):
            raise DataError("儲存日期或市場與行情不符")
        with self.db:
            self.db.execute("DELETE FROM bars WHERE date = ?", (day.isoformat(),))
            self.db.executemany("INSERT INTO bars VALUES (:market,:code,:name,:date,:open,:high,:low,:close,:volume)",
                                [asdict(b) for bars in reports.values() for b in bars])
            self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?)", (day.isoformat(), len(reports["TWSE"]), len(reports["TPEX"])))

    def last_checked(self) -> date | None:
        value = self.db.execute("SELECT MAX(date) FROM sessions").fetchone()[0]
        return date.fromisoformat(value) if value else None

    def latest_date(self) -> str | None:
        return self.db.execute("SELECT MAX(date) FROM bars").fetchone()[0]

    def histories(self, as_of: str) -> dict[tuple[str, str], list[Bar]]:
        """Point-in-time interface for a future backtest; never reads bars after as_of."""
        groups: dict[tuple[str, str], list[Bar]] = {}
        for row in self.db.execute("SELECT * FROM bars WHERE date <= ? ORDER BY date, market, code", (as_of,)):
            bar = Bar(*row)
            groups.setdefault((bar.market, bar.code), []).append(bar)
        return groups

    def close(self):
        self.db.close()
