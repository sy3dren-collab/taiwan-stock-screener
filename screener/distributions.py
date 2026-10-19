"""Official ex-distribution tables, with narrowly supported cash-only events.

These tables are not a complete security lifecycle master. Unsupported events
remain explicit barriers, never guessed stock ratios or cash settlements.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .data import DataError, normalize, number, report_date
from .quality import CorporateAction, import_actions

ENDPOINTS={
    'TWSE':'https://www.twse.com.tw/rwd/zh/exRight/TWT49U',
    'TPEX':'https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ',
}


def source_url(market,start,end):
    params={'response':'json','startDate':start.replace('-','') if market=='TWSE' else start.replace('-','/'),
            'endDate':end.replace('-','') if market=='TWSE' else end.replace('-','/')}
    return ENDPOINTS[market]+'?'+urlencode(params)


def parse_distributions(market,payload,start,end):
    if not isinstance(payload,dict) or str(payload.get('stat','')).lower()!='ok':
        raise DataError(f'{market} 除權息表失敗，不能當成沒有事件')
    tables=payload.get('tables',[payload]);result=[];seen=set();found=False
    date_key='資料日期' if market=='TWSE' else '除權息日期'
    code_key='股票代號' if market=='TWSE' else '代號'
    base_key='開盤競價基準' if market=='TWSE' else '開始交易基準價'
    for table in tables:
        headers=[normalize(x) for x in table.get('fields',[])]
        required=[date_key,code_key,'除權息前收盤價','除權息參考價','權/息',base_key]
        if not all(k in headers for k in required):continue
        found=True;rows=table.get('data')
        if not isinstance(rows,list):raise DataError('官方除權息缺資料列')
        if table.get('totalCount') is not None and int(table['totalCount'])!=len(rows):
            raise DataError('官方除權息回應被分頁／截斷')
        for row in rows:
            if not isinstance(row,list) or len(row)!=len(headers):raise DataError('官方除權息欄位不完整')
            r=dict(zip(headers,row));code=normalize(r[code_key])
            if not re.fullmatch(r'[1-9]\d{3}',code) or (market=='TWSE' and code.startswith('91')):continue
            day=report_date(r[date_key])
            if not start<=day<=end:raise DataError('官方除權息日期超出請求範圍')
            key=(market,code,day)
            if key in seen:raise DataError('同股票同日重複除權息，須核對合併條件')
            seen.add(key);kind=normalize(r['權/息'])
            before,after,reference=(number(r[k]) for k in ('除權息前收盤價','除權息參考價',base_key))
            if min(before,after,reference)<=0:raise DataError('官方除權息參考價不合法')
            cash_only=kind in ('息','除息')
            if market=='TPEX':
                cash_only=cash_only and all(number(r[k])==0 for k in ('每仟股無償配股','現金增資股數'))
            cash=number(r['權值+息值'] if market=='TWSE' else r['現金股利']) if cash_only else None
            if cash_only and (cash<0 or abs(before-after-cash)>.021):
                raise DataError('純現金股利與官方除息參考價不一致')
            result.append({'market':market,'code':code,'date':day,'kind':kind,'before':before,'after':after,
                           'reference':reference,'cash':cash,'supported':cash_only})
    if not found:raise DataError(f'{market} 找不到除權息必要欄位')
    return result


def event_tables(store):
    store.db.executescript('''
    CREATE TABLE IF NOT EXISTS corporate_source_evidence(
      source_url TEXT,payload_sha256 TEXT PRIMARY KEY,observed_at TEXT,payload TEXT);
    CREATE TABLE IF NOT EXISTS distribution_rows(
      market TEXT,code TEXT,date TEXT,payload TEXT,source_sha256 TEXT,
      PRIMARY KEY(market,code,date));
    CREATE TABLE IF NOT EXISTS distribution_sources(
      market TEXT,start TEXT,end TEXT,source_url TEXT,payload_sha256 TEXT,observed_at TEXT,
      PRIMARY KEY(market,start,end));
    ''')


def fetch_distributions(store,start,end,fetch=None):
    """Fetch complete tables; current financial statement fields are never used."""
    event_tables(store);counts={}
    for market in ENDPOINTS:
        url=source_url(market,start,end)
        if fetch is None:
            with urlopen(Request(url,headers={'User-Agent':'TaiwanStockScreener/0.1 (historical research)'}),timeout=40) as response:
                payload=json.loads(response.read().decode('utf-8-sig'))
        else:payload=fetch(url)
        rows=parse_distributions(market,payload,start,end)
        canonical=json.dumps(payload,sort_keys=True,ensure_ascii=False)
        digest=hashlib.sha256(canonical.encode()).hexdigest();now=datetime.now(timezone.utc).isoformat()
        with store.db:
            store.db.execute('INSERT OR IGNORE INTO corporate_source_evidence VALUES (?,?,?,?)',(url,digest,now,canonical))
            store.db.execute('DELETE FROM distribution_rows WHERE market=? AND date BETWEEN ? AND ?',(market,start,end))
            store.db.executemany('INSERT INTO distribution_rows VALUES (?,?,?,?,?)',
                                  [(market,r['code'],r['date'],json.dumps(r,ensure_ascii=False),digest) for r in rows])
            store.db.execute('INSERT OR REPLACE INTO distribution_sources VALUES (?,?,?,?,?,?)',(market,start,end,url,digest,now))
        counts[market]={'rows':len(rows),'cash_only':sum(r['supported'] for r in rows),'payload_sha256':digest,'source_url':url}
    return counts


def reconcile_distributions(store,start,end):
    """Restore X/除息 day references from official bases, not previous prices.

    Cash entitlements are accrued on effective day; no invented payable date.
    Missing/unsupported events remain barriers for diagnostic signals, and stop
    simulation if an already-held position encounters an unexplained event.
    """
    event_tables(store);records=[];restored=0;unsupported=[]
    query='SELECT d.payload,s.source_url FROM distribution_rows d JOIN corporate_source_evidence s ON s.payload_sha256=d.source_sha256 WHERE d.date BETWEEN ? AND ? ORDER BY d.date,d.market,d.code'
    for payload,url in store.db.execute(query,(start,end)).fetchall():
        row=json.loads(payload);key=(row['market'],row['code'],row['date'])
        bar=store.db.execute('SELECT reference FROM bars WHERE market=? AND code=? AND date=?',key).fetchone()
        if bar and bar[0] is not None and abs(bar[0]-row['reference'])>.005:
            raise DataError(f'{key} 日報與除權息開盤基準矛盾，禁止覆寫')
        if bar and bar[0] is None:
            with store.db:store.db.execute('UPDATE bars SET reference=? WHERE market=? AND code=? AND date=?',(row['reference'],*key))
            restored+=1
        if not row['supported']:
            unsupported.append({'market':key[0],'code':key[1],'date':key[2],'kind':row['kind']});continue
        previous=store.db.execute('SELECT date,close FROM bars WHERE market=? AND code=? AND date<? ORDER BY date DESC LIMIT 1',key).fetchone()
        previous_session=store.db.execute('SELECT MAX(date) FROM sessions WHERE date<? AND twse_count>0',(key[2],)).fetchone()[0]
        # Prices before this study may be scattered legacy rows (years away).
        # They are not evidence for the previous session at the left boundary.
        if previous and previous[0]>=start and previous[0]==previous_session and abs(previous[1]-row['before'])>.005:
            raise DataError(f'{key} 除息前收盤與官方日報矛盾，禁止猜測調整比率')
        records.append(asdict(CorporateAction(
            event_id=f'cash-{key[0]}-{key[1]}-{key[2]}',market=key[0],code=key[1],effective_date=key[2],
            announced_date=key[2],kind='distribution',source_url=url,price_factor=row['after']/row['before'],
            cash_per_share=row['cash'],reference_price=row['reference'])))
    import_actions(store,records)
    return {'cash_events_imported':len(records),'references_restored':restored,'unsupported_events':unsupported,
            'limitation':'僅支援核對過的純現金除息；配股、減資、身份變更全集未齊。公告保守採生效日；付款日未知的股利不再投入。'}
