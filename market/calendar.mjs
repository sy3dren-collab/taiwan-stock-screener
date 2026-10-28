export const CALENDAR_URL='https://www.bls.gov/schedule/news_release/bls.ics';
function instant(value,tz){
  const m=value.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(Z)?$/);
  if(!m)throw Error('官方日程時間格式無法解析');
  const expected=Date.UTC(+m[1],+m[2]-1,+m[3],+m[4],+m[5],+(m[6]||0));
  if(m[7])return expected;
  if(!tz)throw Error('官方日程未標可核對時區，不能猜測公布時間');
  const f=new Intl.DateTimeFormat('en-US',{timeZone:tz,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
  let guess=expected;
  for(let i=0;i<3;i++){
    const p=Object.fromEntries(f.formatToParts(new Date(guess)).map(x=>[x.type,x.value]));
    const local=Date.UTC(+p.year,+p.month-1,+p.day,+p.hour,+p.minute,+p.second);
    const adjustment=expected-local;if(!adjustment)return guess;guess+=adjustment;
  }throw Error('官方日程時區轉換無法確認');
}
export function parseEconomicCalendar(text,now){
  if(!text.includes('BEGIN:VCALENDAR'))throw Error('來源不是官方iCalendar日程');
  text=text.replace(/\r?\n[ \t]/g,'');
  const calendarTZ=text.match(/^X-WR-TIMEZONE:([^\r\n]+)/m)?.[1]||text.match(/BEGIN:VTIMEZONE[\s\S]*?^TZID:([^\r\n]+)/m)?.[1];
  const events=[];let skipped=0;
  for(const match of text.matchAll(/BEGIN:VEVENT\r?\n([\s\S]*?)END:VEVENT/g)){
    const lines=match[1].split(/\r?\n/);const title=lines.find(l=>l.startsWith('SUMMARY:'))?.slice(8).replace(/\\n/g,' ').replace(/\\([,;\\])/g,'$1');
    if(!title)continue;
    try{
      if(lines.some(l=>l.startsWith('RRULE:')))throw Error('未展開重複日程');
      const line=lines.find(l=>l.startsWith('DTSTART'));if(!line)throw Error('缺時間');
      const pos=line.indexOf(':'),params=line.slice(0,pos),value=line.slice(pos+1);
      const tz=params.match(/TZID=([^;]+)/)?.[1]?.replace(/^"|"$/g,'')||calendarTZ;
      const stamp=instant(value,tz);
      if(stamp>=now&&stamp<=now+48*3600000)events.push({title,starts_at:new Date(stamp).toISOString(),source:'美國勞工統計局官方日程',source_url:CALENDAR_URL});
    }catch{skipped++;}
  }
  return {status:skipped?'partial':'ok',events:events.sort((a,b)=>a.starts_at.localeCompare(b.starts_at)),unparsed_events:skipped,
    source_url:CALENDAR_URL,window_hours:48,note:'僅BLS未來48小時日程；不涵蓋FOMC、BEA的PCE／GDP或台灣事件，不能視為完整重大事件清單。'};
}
