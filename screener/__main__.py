from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from dataclasses import asdict
import json
import logging
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from .data import DataError, OfficialClient, Store, URLS
from .strategy import Parameters
from .models import MODELS, ModelSettings, required_bars, screen_model
from .execution import Execution, entry_plan

TAIPEI = ZoneInfo("Asia/Taipei")


def default_end() -> date:
    now = datetime.now(TAIPEI)
    return now.date() if now.hour >= 18 else now.date() - timedelta(days=1)


def update(store: Store, client: OfficialClient, end: date, lookback_days: int, start: date | None = None, missing_only: bool = False) -> int:
    last = store.last_checked()
    if start is None:
        start = last - timedelta(days=7) if last else end - timedelta(days=lookback_days)
    count = 0
    day = start
    while day <= end:
        if day.weekday() < 5 and not (missing_only and store.db.execute("SELECT 1 FROM sessions WHERE date = ?", (day.isoformat(),)).fetchone()):
            # Fetch both markets first. A failed source cannot mark a date complete.
            reports = {market: client.daily(market, day) for market in URLS}
            store.save_day(day, reports)
            count += 1
            logging.info("%s 上市 %d / 上櫃 %d", day, len(reports["TWSE"]), len(reports["TPEX"]))
        day += timedelta(days=1)
    return count


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def run(args) -> int:
    output = Path(args.output)
    result = {"schema_version": 1, "generated_at": datetime.now(TAIPEI).isoformat(),
              "requested_through": args.end.isoformat(), "status": "error", "as_of": None,
              "sources": URLS, "candidates": [], "errors": [], "warnings": []}
    store = None
    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        parameters = Parameters(**config)
        model_path = getattr(args, "model_config", None)
        model_settings = ModelSettings(**json.loads(Path(model_path).read_text())) if model_path else ModelSettings()
        active_model = getattr(args, "model", "trend_pullback")
        execution_path = getattr(args, "execution_config", None)
        execution = Execution(**json.loads(Path(execution_path).read_text())) if execution_path else Execution()
        if args.lookback_days < 100:
            raise ValueError("lookback-days 至少為 100，避免預設 MA60 缺少歷史資料")
        if args.end > default_end():
            raise ValueError("不可更新未來日期或尚未收盤發布的當日資料")
        if getattr(args, "start", None) and args.start > args.end:
            raise ValueError("start 不可晚於 end")
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
        store = Store(args.db)
        if args.command == "update":
            ensure_start = getattr(args, "ensure_start", None)
            if ensure_start:
                if ensure_start > args.end:
                    raise ValueError('ensure-start 不可晚於 end')
                update(store, OfficialClient(delay=args.delay), args.end, args.lookback_days, ensure_start, missing_only=True)
            update(store, OfficialClient(delay=args.delay), args.end, args.lookback_days, getattr(args, "start", None))
        as_of = store.db.execute("SELECT MAX(date) FROM bars WHERE date <= ?", (args.end.isoformat(),)).fetchone()[0]
        if not as_of:
            raise DataError("沒有可用的官方歷史行情，請先執行 update")
        result["as_of"] = as_of
        # A long gap is an error, not a silently successful stale screen.
        if (args.end - date.fromisoformat(as_of)).days > 7:
            raise DataError(f"最新行情停留在 {as_of}，距請求日期超過 7 天；請檢查資料來源／長假")
        histories = store.histories(as_of)
        screens = {model: {**screen_model(histories, as_of, parameters, model, model_settings), **details, "model_id": model, "required_bars": required_bars(parameters, model_settings, model)} for model, details in MODELS.items()}
        for model_screen in screens.values():
            for candidate in model_screen["candidates"]:
                candidate["entry_plan"] = entry_plan(candidate, execution, parameters)
        result.update(screens[active_model])
        result.update(strategies=screens, active_model=active_model, user_model="user_range_reclaim", model_parameters=asdict(model_settings))
        result["execution_parameters"] = asdict(execution)
        result["status"] = "ok"
        result["source_warnings"] = []
        if as_of != args.end.isoformat():
            result["warnings"].append(f"請求截至 {args.end}，最新官方交易資料為 {as_of}；可能為休市或資料尚未公布，請核對官方公告。")
            result["source_warnings"].append(result["warnings"][-1])
        if result["shortfall"]:
            result["warnings"].append(f"僅 {len(result['candidates'])} 檔符合全部條件，少於目標 {parameters.target_count} 檔；未放寬條件湊數。")
        if result["sufficient_history_count"] < result["universe_count"]:
            result["warnings"].append(f"{result['universe_count'] - result['sufficient_history_count']} 檔歷史不足 {result['required_bars']} 根，未參與策略判斷。")
        if args.command == "screen":
            result["warnings"].append("此為離線重新選股，未重新查詢官方資料來源。")
            result["source_warnings"].append(result["warnings"][-1])
        return_code = 0
    except Exception as exc:
        result["status"] = "error"
        result["candidates"] = []
        result["errors"].append(str(exc))
        logging.error("更新／選股失敗：%s", exc)
        return_code = 1
    finally:
        if store:
            store.close()
    write_json(output, result)
    return return_code


def main():
    parser = argparse.ArgumentParser(description="台灣股票官方行情更新與波段選股")
    parser.add_argument("command", choices=["update", "screen"])
    parser.add_argument("--db", default=".state/prices.sqlite3")
    parser.add_argument("--output", default="site/results.json")
    parser.add_argument("--config", default="strategy.json")
    parser.add_argument("--model-config", default="models.json")
    parser.add_argument("--model", choices=list(MODELS), default="trend_pullback")
    parser.add_argument("--execution-config", default="execution.json")
    parser.add_argument("--end", type=date.fromisoformat, default=default_end())
    parser.add_argument("--start", type=date.fromisoformat, help="指定補抓起日；省略則增量更新")
    parser.add_argument("--ensure-start", type=date.fromisoformat, help="只補齊指定起日以後缺漏日期，再進行最近日期更新")
    parser.add_argument("--lookback-days", type=int, default=180)
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()
    if args.delay < 1:
        parser.error("--delay 至少為 1 秒，避免頻繁請求官方網站")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(run(args))


if __name__ == "__main__":
    main()
