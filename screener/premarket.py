"""Public-source morning context; no fabricated quotes or generated news."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,time,timedelta,timezone
from email.utils import parsedate_to_datetime
import argparse,hashlib,json,math,re
from pathlib import Path
from urllib.parse import quote,urlparse
from urllib.request import Request,urlopen
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

TAIPEI=ZoneInfo('Asia/Taipei')
SOURCES=json.loads((Path(__file__).resolve().parent.parent/'market_sources.json').read_text())
MARKETS=SOURCES['markets']
FEEDS=SOURCES['feeds']


def fetch(url):
    with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0 TaiwanStockScreener/1.0'}),timeout=15) as response:
        body=response.read(2_000_001)
    if len(body)>2_000_000:raise ValueError('來源回應過大，未接受截斷資料')
    return body


def clean(text):return re.sub(r'\s+',' ',re.sub(r'<[^>]*>','',text or '')).strip()


def safe_url(value):
    parsed=urlparse(value or '')
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('來源連結不合法')
    return value


def parse_quote(payload,market,cutoff,mode='premarket'):
    symbol,name,group,tz,close_at=market
    chart=payload.get('chart',{})
    if chart.get('error') or not chart.get('result'):raise ValueError('行情來源未提供有效結果')
    data=chart['result'][0]
    if data['meta'].get('symbol')!=symbol:raise ValueError('行情代號與請求不符')
    dates=data.get('timestamp',[]);closes=data['indicators']['quote'][0]['close']
    if len(dates)!=len(closes):raise ValueError('行情日期與收盤價筆數不符')
    values={};zone=ZoneInfo(tz)
    for stamp,value in zip(dates,closes):
        if value is None:continue
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise ValueError('收盤價不合法')
        day=datetime.fromtimestamp(stamp,zone).date()
        session_close=datetime.combine(day,time.fromisoformat(close_at),zone)
        if session_close<=cutoff:values[day]=float(value)
    ordered=sorted(values.items())
    if len(ordered)<2:raise ValueError('不足兩次已結束交易時段，不能計算收盤漲跌')
    (previous_day,previous),(day,close)=ordered[-2:]
    quoted_at=None
    if mode=='latest':
        meta=data['meta'];stamp=meta.get('regularMarketTime');value=meta.get('regularMarketPrice')
        if not isinstance(stamp,(int,float)) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise ValueError('缺可驗證時間的最新報價')
        instant=datetime.fromtimestamp(stamp,timezone.utc)
        if instant>cutoff:raise ValueError('最新報價時間在抓取截止時間之後')
        day=instant.astimezone(zone).date();prior=[(d,v) for d,v in ordered if d<day]
        if not prior:raise ValueError('最新報價缺前一交易日收盤比較基準')
        previous_day,previous=prior[-1];close=float(value);quoted_at=instant.astimezone(TAIPEI).isoformat()
    age=(cutoff.astimezone(zone).date()-day).days
    return {'symbol':symbol,'name':name,'group':group,'status':'stale' if age>4 else 'ok',
            'close':close,'previous_close':previous,'change':close-previous,
            'change_pct':100*(close/previous-1),'session_date':day.isoformat(),
            'previous_session_date':previous_day.isoformat(),'exchange_timezone':tz,
            'quote_type':'來源最新報價（可能延遲）' if mode=='latest' else '已結束時段收盤',
            'quoted_at':quoted_at,'currency':data['meta'].get('currency'),'source':'Yahoo Finance 公開日資料（非交易所直連）',
            'source_url':'https://finance.yahoo.com/quote/'+quote(symbol,safe='')+'/',
            'warning':'來源超過4個日曆日未更新；請核對休市或來源狀態' if age>4 else None}


def parse_news(body,source,category,cutoff):
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():raise ValueError('不接受外部實體 XML')
    root=ET.fromstring(body)
    if root.tag not in ('rss','{http://www.w3.org/2005/Atom}feed'):raise ValueError('不是 RSS／Atom 新聞回應')
    result=[]
    for item in root.findall('.//item'):
        title=clean(item.findtext('title'));link=safe_url(item.findtext('link'))
        raw=item.findtext('pubDate')
        if not title or not raw:continue
        published=parsedate_to_datetime(raw)
        if published.tzinfo is None:raise ValueError('新聞缺時區')
        if not cutoff-timedelta(hours=48)<=published<=cutoff:continue
        publisher=clean(item.findtext('source')) or source
        result.append({'title':title,'url':link,'publisher':publisher,'feed_source':source,
                       'category':category,'published_at':published.astimezone(TAIPEI).isoformat()})
    return result


def collect(now=None,fetcher=fetch,mode='premarket'):
    if mode not in ('premarket','latest'):raise ValueError('未知資料模式')
    now=now or datetime.now(TAIPEI)
    if now.tzinfo is None:raise ValueError('需使用有時區時間')
    local=now.astimezone(TAIPEI)
    cutoff=local if mode=='latest' else min(local,datetime.combine(local.date(),time(8,20),TAIPEI))
    def market_task(market):
        url='https://query1.finance.yahoo.com/v8/finance/chart/'+quote(market[0],safe='')+'?interval=1d&range=10d'
        try:
            body=fetcher(url);r=parse_quote(json.loads(body),market,cutoff,mode)
            r['data_url']=url;r['payload_sha256']=hashlib.sha256(body).hexdigest();return r
        except Exception as exc:return {'symbol':market[0],'name':market[1],'group':market[2],'status':'error','error':str(exc),'data_url':url}
    def news_task(feed):
        source,category,url=feed
        try:
            body=fetcher(url);items=parse_news(body,source,category,cutoff)
            return {'source':source,'category':category,'url':url,'status':'ok' if items else 'empty',
                    'items':items,'payload_sha256':hashlib.sha256(body).hexdigest()}
        except Exception as exc:return {'source':source,'category':category,'url':url,'status':'error','error':str(exc),'items':[]}
    with ThreadPoolExecutor(max_workers=6) as pool:
        markets=list(pool.map(market_task,MARKETS));feeds=list(pool.map(news_task,FEEDS))
    news=[];seen=set()
    for item in sorted([i for f in feeds for i in f['items']],key=lambda x:x['published_at'],reverse=True):
        key=clean(item['title']).casefold()
        if key not in seen:seen.add(key);news.append(item)
    failed=sum(m['status']!='ok' for m in markets)+sum(f['status']!='ok' for f in feeds)
    healthy=sum(m['status']=='ok' for m in markets)+sum(f['status']=='ok' for f in feeds)
    return {'schema_version':1,'status':'ok' if not failed else 'partial' if healthy else 'error',
            'mode':mode,'generated_at':local.isoformat(),'briefing_date':local.date().isoformat(),'cutoff_at':cutoff.isoformat(),
            'news_window_hours':48,'markets':markets,'feeds':[{k:v for k,v in f.items() if k!='items'} for f in feeds],
            'news':{c:[n for n in news if n['category']==c][:20] for c in ('台灣','國際')},
            'notes':['盤前模式截止於台北08:20，僅用已結束時段；最新模式使用來源最新可取得報價，可能延遲，非逐筆即時。',
                     '漲跌比較該指數最近兩個已結束交易時段；各市場休市日不同，請看每張卡片日期。',
                     '新聞為來源RSS標題與原文連結，依發布時間整理，未推論台股漲跌；英文標題保留原文。',
                     '新聞限截止前48小時內；RSS不是完整新聞歷史庫。週末與休市日也須核對資料日期。',
                     '自動更新目標為週一至週五台北08:10；GitHub Actions可能延遲，請核對產生時間。']}


def main():
    from .__main__ import write_json
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--mode',choices=['premarket','latest'],default='premarket')
    args=parser.parse_args();result=collect(mode=args.mode);write_json(Path('site/premarket.json'),result)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    write_json(Path('site/premarket-runs')/(stamp+'.json'),result)
    print(json.dumps({'status':result['status'],'date':result['briefing_date'],
                      'quotes':sum(m['status']=='ok' for m in result['markets']),
                      'news':{k:len(v) for k,v in result['news'].items()}},ensure_ascii=False))
    if result['status']!='ok':raise SystemExit(1)


if __name__=='__main__':main()
