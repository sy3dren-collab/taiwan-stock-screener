// The same deterministic, source-backed summary is used by publishing and display.
const number=n=>Number(n).toLocaleString('zh-TW',{maximumFractionDigits:2});
const signed=n=>(n>0?'+':'')+number(n);
const unit=m=>m.symbol==='^TNX'?'%（殖利率）':m.symbol==='TWD=X'?'新台幣／美元':m.symbol==='TSM'?'美元／ADR':m.symbol==='CL=F'?'美元／桶':m.symbol==='GC=F'?'美元／盎司':m.symbol.startsWith('^')?'點':(m.unit||m.currency||'');
const PRIORITY=['^SOX','^IXIC','TSM','^GSPC','^DJI','^VIX','TWD=X','^TNX','^TWII'];
const THEMES={
  '半導體／權值股':'追蹤半導體與大型電子股消息，以及費半、台積電ADR的變化。',
  '央行／重要經濟數據':'核對政策或數據公布時間；實際值與市場預期不同，影響也可能不同。',
  '地緣／政策風險':'留意政策或事件後續公告，以及能源、避險資產與波動指標的變化。',
  '股匯市／資金':'對照股市與匯率的實際變動，不將單一市場方向直接當成台指期訊號。'
};

export function buildMorningBrief(data){
  const raw=data.markets||[];
  const metrics=raw.filter(m=>m.status==='ok'&&[m.close,m.change,m.change_pct].every(Number.isFinite))
    .sort((a,b)=>(PRIORITY.indexOf(a.symbol)<0?99:PRIORITY.indexOf(a.symbol))-(PRIORITY.indexOf(b.symbol)<0?99:PRIORITY.indexOf(b.symbol)))
    .map(m=>({...m,value_text:number(m.close)+' '+unit(m),change_text:signed(m.change_pct)+'%',change_value_text:signed(m.change)+' '+(m.symbol==='^TNX'?'個百分點':unit(m))}));
  const bySymbol=new Map(metrics.map(m=>[m.symbol,m])),overview=[];
  const us=['^DJI','^GSPC','^IXIC','^SOX'].map(s=>bySymbol.get(s)).filter(Boolean);
  const usDates=[...new Set(us.map(m=>m.session_date))];
  if(us.length)overview.push({text:`美股交易日 ${usDates.join('、')}${usDates.length>1?'（日期不一致，須分別閱讀）':''}，四指數取得 ${us.length}/4 項：${us.filter(m=>m.change_pct>0).length} 漲、${us.filter(m=>m.change_pct<0).length} 跌、${us.filter(m=>m.change_pct===0).length} 持平。`+us.map(m=>`${m.name} ${signed(m.change_pct)}%`).join('；')+'。',symbols:us.map(m=>m.symbol)});
  const sox=bySymbol.get('^SOX'),nasdaq=bySymbol.get('^IXIC');
  if(sox&&nasdaq&&sox.session_date===nasdaq.session_date)overview.push({text:`同一交易日，費半漲跌幅減去那斯達克漲跌幅為 ${signed(sox.change_pct-nasdaq.change_pct)} 個百分點；僅比較已知行情，不代表台指期開盤幅度。`,symbols:['^SOX','^IXIC']});
  for(const [symbol,note] of [['TSM','ADR與台股現股的交易時段、匯率不同，不能直接換成現股漲幅。'],['^VIX','VIX是波動預期指標，上升不等於股市上漲。'],['TWD=X','數值上升表示美元相對新台幣走強。'],['^TNX','這是美國10年期殖利率指標，不是股票指數。']]){
    const m=bySymbol.get(symbol);if(m)overview.push({text:`${m.name} ${m.value_text}，較前次 ${m.change_text}。${note}`,symbols:[symbol]});
  }
  const futures=['ok','stale'].includes(data.futures?.status)?(data.futures.rows||[]).filter(r=>Number.isFinite(r.last)).map(r=>({...r,
    range_points:Number.isFinite(r.high)&&Number.isFinite(r.low)&&r.high>=r.low?r.high-r.low:null})):[];
  if(futures.length){const month=futures[0].contract_month;const rows=futures.filter(f=>f.contract_month===month);overview.unshift({text:`台指期公開交易報表 TX ${month}：`+rows.map(f=>`${f.session} ${number(f.last)} 點${f.range_points===null?'':`，報表高低差 ${number(f.range_points)} 點`}`).join('；')+'。這是報表資料，不是即時價格。',symbols:[]});}
  const seen=new Set(),headlines=[];
  for(const category of ['台灣','國際']){
    let count=0;
    for(const item of data.news?.[category]||[]){
      if(seen.has(item.title)||count>=3)continue;seen.add(item.title);count++;
      const excerpt=String(item.description||'').trim();
      headlines.push({...item,category,excerpt:excerpt||null,
        summary_kind:excerpt?'來源公開摘要摘錄':'僅取得標題，來源未提供摘要；不推測內文',
        watch_points:(item.relevance_tags||[]).map(t=>THEMES[t]).filter(Boolean)});
    }
  }
  if(!metrics.length)overview.push({text:'本次沒有可驗證的新近行情，無法形成數據概況；請查看來源錯誤，不將缺資料當作持平。',symbols:[]});
  const missing=raw.filter(m=>!metrics.some(q=>q.symbol===m.symbol)).map(m=>({name:m.name,reason:m.error||m.warning||'資料不足或過期'}));
  const day=data.briefing_date,weekend=day&&[0,6].includes(new Date(day+'T00:00:00Z').getUTCDay());
  return {schema_version:1,generated_at:data.generated_at,briefing_date:day,
    method:'僅依可驗證數值、公開RSS摘要與明示的主題規則整理，未生成未知事實或漲跌預測。',
    session_note:weekend?'今天是週末，這是市場背景整理，不代表台股今日開盤。':'請另核對台灣休市與期貨到期公告。',
    coverage:{quotes_available:metrics.length,quotes_total:raw.length,news_selected:headlines.length},
    overview,metrics,futures,headlines,missing,
    calendar:data.calendar||{status:'unavailable',events:[],error:'尚未取得可核對的近期事件日程，不能推定今天沒有重大數據。'}};
}
