"""Net portfolio returns and complete-trade statistics, with sample uncertainty."""
from collections import defaultdict
from datetime import date
import math
from statistics import mean


def metrics(curve,trades,initial,costs=0):
    closed=len(trades);wins=[t for t in trades if t['net_pnl']>0];losses=[t for t in trades if t['net_pnl']<0]
    profit=sum(t['net_pnl'] for t in wins);loss=-sum(t['net_pnl'] for t in losses)
    peak=initial;dd=0;losing=longest=0;drawdowns=[]
    for point in curve:
        peak=max(peak,point['equity']);d=1-point['equity']/peak;dd=max(dd,d);drawdowns.append({'date':point['date'],'drawdown':d})
    for t in trades:losing=losing+1 if t['net_pnl']<0 else 0;longest=max(longest,losing)
    monthly=[];yearly=[]
    for size,out in ((7,monthly),(4,yearly)):
        groups=defaultdict(list)
        for point in curve[1:]:groups[point['date'][:size]].append(point)
        base=initial
        for period,points in groups.items():
            end=points[-1]['equity'];out.append({'period':period,'net_return':end/base-1 if base else None});base=end
    w=len(wins)/closed if closed else None
    interval=None
    if closed:
        z=1.96;den=1+z*z/closed;center=(w+z*z/(2*closed))/den
        width=z*math.sqrt(w*(1-w)/closed+z*z/(4*closed*closed))/den
        interval=[max(0,center-width),min(1,center+width)]
    days=(date.fromisoformat(curve[-1]['date'])-date.fromisoformat(curve[0]['date'])).days
    final=curve[-1]['equity'];net=final/initial-1
    return {'closed_count':closed,'winners':len(wins),'losers':len(losses),'breakeven_trades':closed-len(wins)-len(losses),
            'win_rate':w,'win_rate_wilson_95':interval,'average_profit':mean(t['net_pnl'] for t in wins) if wins else None,
            'average_loss':mean(t['net_pnl'] for t in losses) if losses else None,
            'expectancy':mean(t['net_pnl'] for t in trades) if closed else None,'profit_factor':profit/loss if loss else None,
            'net_return':net,'annualized_return':(final/initial)**(365.25/days)-1 if days>0 and final>0 else None,
            'max_drawdown':dd,'average_holding_sessions':mean(t['holding_sessions'] for t in trades) if closed else None,
            'longest_losing_streak':longest,'total_costs':costs,'return_adding_back_costs':(final+costs)/initial-1,
            'before_cost_note':'同一批模型交易加回費稅與滑價的會計比較；不是重新分配資金的無成本回測',
            'monthly':monthly,'yearly':yearly,'drawdown_curve':drawdowns,
            'sample_warning':'樣本不足100筆，勝率即使85%也不代表可信' if closed<100 else '勝率仍非未來保證'}
