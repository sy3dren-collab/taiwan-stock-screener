"""Fail-closed dataset evidence, corporate actions and bounded official backfill."""
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
from urllib.parse import urlparse

from .data import DataError, OfficialClient, Store, URLS

@dataclass(frozen=True)
class CorporateAction:
    event_id: str
    market: str
    code: str
    effective_date: str
    announced_date: str
    kind: str
    source_url: str
    price_factor: float = 1.0
    share_factor: float = 1.0
    cash_per_share: float = 0.0
    reference_price: float | None = None
    payable_date: str | None = None
    new_market: str | None = None
    new_code: str | None = None
    settlement_price: float | None = None

    def __post_init__(self):
        if not self.event_id or self.market not in URLS or not self.code.isdigit() or len(self.code)!=4:
            raise DataError('公司行動識別不合法')
        if date.fromisoformat(self.announced_date)>date.fromisoformat(self.effective_date):raise DataError('公告日不可晚於生效日')
        parsed=urlparse(self.source_url)
        if parsed.scheme!='https' or parsed.hostname not in ('www.twse.com.tw','www.tpex.org.tw','mops.twse.com.tw'):
            raise DataError('公司行動須附官方 HTTPS 來源')
        if self.kind not in ('distribution','split','delisting','identity'):raise DataError('不支援的公司行動，須人工取得完整官方條件')
        for key in ('price_factor','share_factor','cash_per_share'):
            value=getattr(self,key)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:raise DataError('公司行動數值不合法')
        if self.price_factor<=0 or self.share_factor<=0:raise DataError('調整比率必須為正')
        for value in (self.reference_price,self.settlement_price):
            if value is not None and (not math.isfinite(value) or value<0):raise DataError('公司行動價格不合法')
        if self.reference_price==0:raise DataError('參考價格不可為零')
        if self.payable_date and date.fromisoformat(self.payable_date)<date.fromisoformat(self.effective_date):raise DataError('支付日不可早於生效日')
        if self.kind=='delisting' and self.settlement_price is None:raise DataError('未知下市清算價，禁止自行填價')
        if self.kind=='identity' and (self.new_market not in URLS or not self.new_code):raise DataError('代碼轉換須有官方新市場與新代號')


def event_table(store):
    store.db.execute('CREATE TABLE IF NOT EXISTS corporate_actions(event_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    store.db.commit()


def actions(store):
    event_table(store)
    return [CorporateAction(**json.loads(row[0])) for row in store.db.execute('SELECT payload FROM corporate_actions ORDER BY event_id')]


def import_actions(store, records):
    parsed=[CorporateAction(**row) for row in records]
    if len({a.event_id for a in parsed})!=len(parsed):raise DataError('重複公司行動識別碼')
    event_table(store)
    existing=actions(store)
    for i,a in enumerate(parsed):
        for other in existing+parsed[:i]:
            if a.event_id!=other.event_id and (a.market,a.code,a.effective_date)==(other.market,other.code,other.effective_date) and a.kind!='identity' and other.kind!='identity':raise DataError('同日重複經濟事件或修訂缺版本語意，禁止重複套用；須核對官方合併條件')
    with store.db:
        for a in parsed:
            payload=json.dumps(asdict(a),sort_keys=True,ensure_ascii=False)
            old=store.db.execute('SELECT payload FROM corporate_actions WHERE event_id=?',(a.event_id,)).fetchone()
            if old and old[0]!=payload:raise DataError('公司行動修訂須新識別碼，保留舊證據不可覆寫')
            store.db.execute('INSERT OR IGNORE INTO corporate_actions VALUES (?,?)',(a.event_id,payload))


def adjusted_history(bars, day, events):
    """Only actions already effective AND announced by day can change signal history."""
    from dataclasses import replace
    known=[a for a in events if a.announced_date<=day and a.effective_date<=day]
    output=[]
    for b in bars:
        if b.date>day:continue
        factor=math.prod(a.price_factor for a in known if a.market==b.market and a.code==b.code and b.date<a.effective_date)
        volume_factor=math.prod(a.share_factor for a in known if a.market==b.market and a.code==b.code and b.date<a.effective_date)
        output.append(replace(b,volume=round(b.volume*volume_factor),open=b.open*factor,high=b.high*factor,low=b.low*factor,close=b.close*factor,
                              reference=b.reference*factor if b.reference is not None else None))
    return output


def signal_histories(histories, day, events):
    from dataclasses import replace
    result={}
    identities=sorted((a for a in events if a.kind=='identity' and a.announced_date<=day and a.effective_date<=day),key=lambda a:a.effective_date)
    for bars in histories.values():
        for b in adjusted_history(bars,day,events):
            key=(b.market,b.code)
            for a in identities:
                if key==(a.market,a.code) and b.date<a.effective_date:key=(a.new_market,a.new_code)
            result.setdefault(key,[]).append(replace(b,market=key[0],code=key[1]))
    for bars in result.values():
        bars.sort(key=lambda b:b.date)
        if len({b.date for b in bars})!=len(bars):raise DataError('代碼轉換後出現同日重複行情，禁止猜測合併')
    return result


def fingerprint(store, end):
    digest=hashlib.sha256()
    for row in store.db.execute('SELECT * FROM bars WHERE date<=? ORDER BY date,market,code',(end,)):
        digest.update(json.dumps(row,separators=(',',':'),ensure_ascii=False).encode()+b'\n')
    for a in actions(store):
        if a.effective_date<=end and a.announced_date<=end:digest.update(json.dumps(asdict(a),sort_keys=True).encode())
    return digest.hexdigest()


def audit_dataset(store, study):
    start,end=study['data_start'],study['as_of'];issues=[]
    checked={r[0] for r in store.db.execute('SELECT date FROM sessions WHERE date BETWEEN ? AND ?',(start,end))}
    missing=[];day=date.fromisoformat(start)
    while day<=date.fromisoformat(end):
        if day.weekday()<5 and day.isoformat() not in checked:missing.append(day.isoformat())
        day+=timedelta(days=1)
    if missing:issues.append(f'尚缺 {len(missing)} 個工作日官方日報／休市證據')
    row=store.db.execute('SELECT MIN(date),MAX(date),COUNT(*),SUM(turnover IS NULL),SUM(reference IS NULL) FROM bars WHERE date BETWEEN ? AND ?',(start,end)).fetchone()
    if row[3]:issues.append(f'{row[3]} 筆缺官方成交金額；禁止用收盤×成交量補值')
    if row[4]:issues.append(f'{row[4]} 筆缺當日官方漲跌參考價；公司行動及漲跌停無法完整核對')
    expected=2*len(checked)
    proofs=store.db.execute('SELECT COUNT(*) FROM source_batches WHERE date BETWEEN ? AND ?',(start,end)).fetchone()[0]
    if proofs<expected:issues.append(f'{expected-proofs} 份市場日報缺來源雜湊／抓取時間證據，須補抓')
    if store.db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':issues.append('SQLite 完整性檢查失敗')
    mismatch=store.db.execute("""SELECT COUNT(*) FROM sessions s WHERE s.date BETWEEN ? AND ? AND
      (s.twse_count!=(SELECT COUNT(*) FROM bars b WHERE b.date=s.date AND b.market='TWSE') OR
       s.tpex_count!=(SELECT COUNT(*) FROM bars b WHERE b.date=s.date AND b.market='TPEX'))""",(start,end)).fetchone()[0]
    if mismatch:issues.append(f'{mismatch} 日行情筆數不完整')
    # Only an audited official adapter may write coverage; importing individual events is insufficient.
    store.db.execute('CREATE TABLE IF NOT EXISTS lifecycle_coverage(market TEXT,kind TEXT,start TEXT,end TEXT,source_url TEXT,payload_sha256 TEXT,PRIMARY KEY(market,kind,start,end))')
    coverage={(r[0],r[1]) for r in store.db.execute('SELECT market,kind FROM lifecycle_coverage WHERE start<=? AND end>=? AND LENGTH(payload_sha256)=64',(start,end))}
    required={(market,kind) for market in URLS for kind in ('distribution','split','delisting','identity')}
    if not required.issubset(coverage):issues.append('尚缺完整官方分割／減資／下市及代碼轉換事件母表，未宣稱公司行動已全部處理')
    data_ready=not issues
    if study.get('holdout_status')!='pristine':issues.append('最近一年已使用，封存樣本外已污染，禁止最終晉級')
    return {'status':'blocked' if issues else 'ready','research_ready':data_ready,'requested_start':start,'requested_end':end,
            'actual_start':row[0],'actual_end':row[1],'bars':row[2], 'missing_turnover':row[3] or 0,
            'missing_reference':row[4] or 0,'missing_weekdays':len(missing),'first_missing_dates':missing[:15],
            'source_proofs':proofs,'issues':issues,'data_sha256':fingerprint(store,end),
            'corporate_actions_imported':len(actions(store)), 'trading_sessions':store.db.execute('SELECT COUNT(DISTINCT date) FROM bars WHERE date BETWEEN ? AND ?',(start,end)).fetchone()[0]}


def backfill(store, study, budget, delay=1.0):
    if delay<1:raise ValueError('官方請求間隔至少一秒')
    began=time.monotonic();day=date.fromisoformat(study['data_start']);end=date.fromisoformat(study['as_of'])
    done=requests=0;error=None;last=None
    limits=(int(budget['max_backfill_days']),int(budget['max_requests']),float(budget['backfill_seconds']))
    if min(limits)<=0 or limits[0]>250 or limits[1]>500 or limits[2]>1800:raise ValueError('回補預算須為正，最多250日／500請求／1800秒')
    client=OfficialClient(delay=delay,retries=2,timeout=20,request_budget=limits[1],deadline=began+limits[2])
    while day<=end:
        if day.weekday()<5:
            proof=store.db.execute('SELECT COUNT(*) FROM source_batches WHERE date=?',(day.isoformat(),)).fetchone()[0]
            unknown=store.db.execute('SELECT COUNT(*) FROM bars WHERE date=? AND turnover IS NULL',(day.isoformat(),)).fetchone()[0]
            if proof!=2 or unknown:
                if done>=limits[0] or requests+2>limits[1] or time.monotonic()-began>=limits[2]-2:break
                try:
                    reports={}
                    for market in URLS:
                        remaining=limits[2]-(time.monotonic()-began)
                        if remaining<1:raise DataError('本輪時間預算已用完；未儲存半日資料')
                        client.timeout=min(20,remaining);requests+=1
                        try:reports[market]=client.daily(market,day)
                        finally:requests=getattr(client,'request_count',requests)
                    store.save_day(day,reports,dict(client.provenance));done+=1;last=day.isoformat()
                    print(f'official {day} TWSE={len(reports["TWSE"])} TPEX={len(reports["TPEX"])}',flush=True)
                except Exception as exc:
                    if '預算已用完' not in str(exc):error=str(exc)
                    break
        day+=timedelta(days=1)
    return {'status':'error' if error else 'complete' if day>end else 'partial','completed_dates':done,
            'http_requests':requests,'last_completed':last,'elapsed_seconds':round(time.monotonic()-began,2),
            'error':error,'reason':'source_error' if error else 'complete' if day>end else 'resource_budget',
            'next_run':'相同命令只補未完成／缺成交金額的日期'}


def main():
    p=argparse.ArgumentParser(description='官方資料品質、公司行動證據及有界五年回補')
    p.add_argument('command',choices=['audit','backfill','import-actions']);p.add_argument('--db',default='.state/prices.sqlite3')
    p.add_argument('--config',default='naked_k.json');p.add_argument('--events-file');p.add_argument('--output',default='site/data-quality.json')
    a=p.parse_args();cfg=json.loads(Path(a.config).read_text());Path(a.db).parent.mkdir(parents=True,exist_ok=True);s=Store(a.db)
    try:
        if a.command=='import-actions':import_actions(s,json.loads(Path(a.events_file).read_text()))
        result={'schema_version':1,'generated_at':datetime.now(timezone.utc).isoformat()}
        s.db.execute('CREATE TABLE IF NOT EXISTS ingestion_runs(created_at TEXT,payload TEXT)')
        if a.command=='backfill':
            result['backfill']=backfill(s,cfg['study'],cfg['budget'])
            with s.db:s.db.execute('INSERT INTO ingestion_runs VALUES (?,?)',(result['generated_at'],json.dumps(result['backfill'],ensure_ascii=False)))
        else:
            previous=s.db.execute('SELECT payload FROM ingestion_runs ORDER BY rowid DESC LIMIT 1').fetchone()
            if previous:result['backfill']=json.loads(previous[0])
        result.update(audit_dataset(s,cfg['study']))
    finally:s.close()
    from .__main__ import write_json
    write_json(Path(a.output),result)
    if result.get('backfill',{}).get('status')=='error':raise SystemExit(1)

if __name__=='__main__':main()
