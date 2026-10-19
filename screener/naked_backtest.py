"""Raw-price execution, point-in-time signals and conservative intraday sequencing."""
from bisect import bisect_right
from dataclasses import asdict, dataclass
import math
import time

from .data import DataError
from .execution import Execution,commission,fill_price,sell_proceeds,tick_price
from .naked import NakedParameters,screen
from .performance import metrics
from .strategy import pivots

class ResearchBudgetExceeded(RuntimeError):pass

@dataclass(frozen=True)
class Risk:
    risk_budget:float=.01
    trailing_activation_r:float=1.5
    trailing_buffer:float=.005
    max_unquoted_sessions:int=3
    def __post_init__(self):
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in asdict(self).values()):raise ValueError('風控參數必須為正有限數值')
        if self.risk_budget>=1 or self.trailing_buffer>=1 or not isinstance(self.max_unquoted_sessions,int):raise ValueError('風控比例或停牌期限不合法')


def simulate(histories,p:NakedParameters,e:Execution,risk:Risk,model,start,end,events=(),deadline=None,signal_provider=None,entry_cutoff=None,benchmark=False):
    histories={k:sorted((b for b in bars if b.date<=end),key=lambda b:b.date) for k,bars in histories.items()}
    for bars in histories.values():
        if len({b.date for b in bars})!=len(bars):raise DataError('重複 K 棒')
    all_days=sorted({b.date for bars in histories.values() for b in bars});days=[d for d in all_days if start<=d<=end]
    if len(days)<2:raise DataError('模擬資料不足')
    index={k:[b.date for b in bars] for k,bars in histories.items()}
    raw={}
    for k,bars in histories.items():
        for b in bars:raw.setdefault(b.date,{})[k]=b
    first=all_days.index(days[0]);initial_day=all_days[first-1] if first else days[0]
    cash=float(e.initial_capital);positions={};orders=[];trades=[];receivables=[];costs=0;rejected={};deferred=[];curve=[{'date':initial_day,'equity':cash,'cash':cash,'positions':0}]
    latest={k:next((b for b in reversed(bars) if b.date<days[0]),None) for k,bars in histories.items()}
    applied=set()
    def reject(reason):rejected[reason]=rejected.get(reason,0)+1
    def close(key,pos,day,reference,reason,session,settlement=False):
        nonlocal cash,costs
        price=reference if settlement else fill_price(reference,False,e)
        if settlement:proceeds=price*pos['quantity'];fee=tax=0
        else:proceeds,fee,tax=sell_proceeds(price,pos['quantity'],e)
        costs+=fee+tax+(reference-price)*pos['quantity']
        cash=round(cash+proceeds,6)
        pnl=round(proceeds+pos['dividends']-pos['cost'],6)
        trades.append({**pos,'exit_date':day,'exit_price':price,'exit_fee':fee,'sell_tax':tax,'exit_reason':reason,
                       'holding_sessions':session-pos['entry_index']+1,'net_pnl':pnl,'net_return':pnl/pos['cost']})
        del positions[key]
    for session,day in enumerate(days):
        if deadline and time.monotonic()>=deadline:raise ResearchBudgetExceeded('本輪運算預算已用完；未產出部分績效冒充完整回測')
        quotes=raw[day]
        for item in receivables:
            if not item['paid'] and item['payable_date'] and item['payable_date']<=day:
                cash+=item['amount'];item['paid']=True
        todays=sorted((a for a in events if a.effective_date==day and a.announced_date<=day and a.event_id not in applied),key=lambda a:a.kind=='identity')
        for a in todays:
            applied.add(a.event_id);key=(a.market,a.code);pos=positions.get(key)
            if not pos:continue
            pos['corporate_actions'].append(a.event_id)
            if a.kind=='delisting':
                amount=a.settlement_price*pos['quantity']
                close(key,pos,day,a.settlement_price,'官方下市清算',session,True)
                if not a.payable_date or a.payable_date>day:
                    cash-=amount;receivables.append({'amount':amount,'payable_date':a.payable_date,'paid':False})
                continue
            if a.kind=='identity':
                new=(a.new_market,a.new_code)
                if new in positions:raise DataError('代碼轉換遇重複部位，須完整證券生命週期處理')
                positions[new]=positions.pop(key);pos['market'],pos['code']=new
                if key in latest:latest[new]=latest[key]
                continue
            if a.cash_per_share:
                dividend=pos['quantity']*a.cash_per_share;pos['dividends']+=dividend
                if a.payable_date and a.payable_date<=day:cash+=dividend
                else:receivables.append({'amount':dividend,'payable_date':a.payable_date,'paid':False})
            quantity=pos['quantity']*a.share_factor
            if abs(quantity-round(quantity))>1e-7:raise DataError('公司行動產生零股小數，缺官方畸零股補償條件')
            pos['quantity']=int(round(quantity))
            for field in ('stop','target','basis','initial_risk'):pos[field]*=a.price_factor
        # Fixed closing list; no replacement after seeing today's unavailable orders.
        for signal in orders:
            key=(signal['market'],signal['code']);bar=quotes.get(key)
            if any((a.market,a.code)==key for a in todays):reject('進場日公司行動，取消舊基準委託');continue
            if key in positions or len(positions)>=e.max_positions:reject('部位上限');continue
            if not bar or bar.volume<=0 or bar.reference is None:reject('無有效開盤或參考價');continue
            up=tick_price(bar.reference*1.1,False)
            if bar.open>=up:reject('開盤漲停，保守不成交');continue
            if bar.open>signal['close']*(1+e.max_entry_gap):reject('跳空超過追價上限');continue
            price=fill_price(bar.open,True,e);distance=price-signal['stop']
            if not benchmark and (distance<=0 or distance/price>p.max_risk or (signal['target']-price)/distance<p.min_reward_risk):reject('開盤風報比不合格');continue
            budget=min(cash,e.initial_capital/e.max_positions)
            capacity=int(signal['metrics']['average_volume']*e.max_participation/e.lot_size)*e.lot_size
            shares=min(int(budget/price/e.lot_size)*e.lot_size,capacity)
            if not benchmark:shares=min(shares,int(e.initial_capital*risk.risk_budget/distance/e.lot_size)*e.lot_size)
            while shares>0 and shares*price+commission(shares*price,e)>budget:shares-=e.lot_size
            if shares<=0:reject('整張資金或風險預算不足');continue
            fee=commission(shares*price,e);cost=shares*price+fee;cash-=cost;costs+=fee+(price-bar.open)*shares
            positions[key]={'market':key[0],'code':key[1],'name':signal['name'],'signal_date':signal['date'],
               'entry_date':day,'entry_index':session,'entry_market':key[0],'entry_code':key[1],'entry_price':price,
               'quantity':shares,'entry_quantity':shares,'entry_fee':fee,'cost':cost,'basis':price,'initial_risk':distance,
               'stop':signal['stop'],'initial_stop':signal['stop'],'target':signal['target'],'dividends':0,
               'corporate_actions':[],'unquoted':0,'pending_exit':None,'model_id':model,'entry_reasons':signal.get('reasons',[])}
        for key,pos in list(positions.items()):
            bar=quotes.get(key);holding=session-pos['entry_index']+1
            if not bar or bar.volume<=0:
                pos['unquoted']+=1
                if pos['unquoted']>risk.max_unquoted_sessions:raise DataError(f'{key} 持倉連續缺價，禁止沿用舊價或刪除虧損交易')
                if not benchmark and holding>=e.max_hold_sessions:pos['pending_exit']='到期但停牌待出場'
                continue
            pos['unquoted']=0
            if bar.reference is None:raise DataError(f'{key} 缺當日參考價，無法確認公司行動及成交限制')
            previous=latest.get(key)
            matching=[a for a in todays if (a.market,a.code)==key]
            expected=previous.close*math.prod(a.price_factor for a in matching) if previous else bar.reference
            if previous and abs(bar.reference-expected)>.005:
                raise DataError(f'{key} 參考價不連續或事件比率不符，停止完整回測')
            if any(a.reference_price is not None and abs(a.reference_price-bar.reference)>.005 for a in matching):
                raise DataError('公司行動官方參考價不符')
            down=tick_price(bar.reference*.9,True)
            if bar.open<=down:
                deferred.append({'date':day,'code':key[1],'reason':'開盤跌停，保守不賣出'})
                if bar.low<=pos['stop'] or holding>=e.max_hold_sessions:pos['pending_exit']='限制解除後出場'
                continue
            if benchmark:continue
            if pos['pending_exit'] or holding>=e.max_hold_sessions:
                close(key,pos,day,bar.open,pos['pending_exit'] or '第20日到期開盤',session);continue
            if bar.open<=pos['stop']:close(key,pos,day,bar.open,'跳空停損',session);continue
            if bar.open>=pos['target']:close(key,pos,day,bar.open,'開盤達目標',session);continue
            # When order is unknown within the same bar, always take the adverse stop first.
            if bar.low<=pos['stop']:close(key,pos,day,pos['stop'],'盤中結構停損（同根衝突停損優先）',session);continue
            if bar.high>=pos['target']:close(key,pos,day,pos['target'],'盤中目標',session);continue
        for key,bar in quotes.items():latest[key]=bar
        # Built-in rules need only the configured past window. Custom providers retain full history.
        known={}
        for k,bars in histories.items():
            end_index=bisect_right(index[k],day)
            known[k]=bars[max(0,end_index-p.lookback) if signal_provider is None else 0:end_index]
        from .quality import signal_histories
        for key,pos in positions.items():
            bar=quotes.get(key)
            if not bar:continue
            if not benchmark and bar.close>=pos['basis']+risk.trailing_activation_r*pos['initial_risk']:
                adjusted=signal_histories(known,day,events).get(key,[])
                _,lows=pivots(adjusted[-p.structure_days:],p.pivot_radius)
                if lows:pos['stop']=max(pos['stop'],min(bar.close,lows[-1].low)*(1-risk.trailing_buffer))
        value=cash+sum(x['amount'] for x in receivables if not x['paid'])
        for key,pos in positions.items():
            bar=latest.get(key)
            if not bar:raise DataError('持倉無合法估值價格')
            mark=fill_price(bar.close,False,e);value+=sell_proceeds(mark,pos['quantity'],e)[0]
        curve.append({'date':day,'equity':round(value,6),'cash':round(cash,6),'positions':len(positions)})
        if entry_cutoff and day>entry_cutoff:orders=[];continue
        signals=(signal_provider(known,day) if signal_provider else screen(known,day,model,p,events))['candidates']
        if any(s['date']!=day for s in signals):raise DataError('訊號使用非當日資料')
        orders=[s for s in signals if (s['market'],s['code']) not in positions][:max(0,e.max_positions-len(positions))]
    if any(latest[k].date!=days[-1] for k in positions):raise DataError('期末持倉缺價，禁止沿用舊價估算可信報酬')
    estimated=0
    for key,pos in positions.items():
        reference=latest[key].close;price=fill_price(reference,False,e)
        _,fee,tax=sell_proceeds(price,pos['quantity'],e);estimated+=fee+tax+(reference-price)*pos['quantity']
    result=metrics(curve,trades,e.initial_capital,costs+estimated)
    return {'model_id':model,'start':days[0],'end':days[-1],'metrics':result,'closed_trades':trades,
            'open_positions':list(positions.values()),'equity_curve':curve,'rejected_orders':rejected,'deferred_exits':deferred,
            'receivables':receivables,'limitations':['日線限價與滑價為保守撮合模型，未模擬開盤佇列／部分成交。','5～20日為正常目標，風險停損或目標可更早，停牌與跌停可能更晚。','股息採已知應收款；未指定支付日不得動用，未模擬個人所得稅。']}
