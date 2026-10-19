from dataclasses import replace,asdict
import math,time,unittest
from screener.data import Bar,DataError
from screener.naked import NakedParameters,evaluate,screen
from screener.execution import Execution,fill_price,sell_proceeds
from screener.naked_backtest import Risk,ResearchBudgetExceeded,simulate
from screener.quality import CorporateAction
from screener.performance import metrics
from test_backtest import dates as make_dates

def dates(n=160):return make_dates(n)


def bars(n=135):
    return [Bar('TWSE','2330','純測試',d,100,100.5,99.5,100,10000000,1000000000,100) for d in dates(n)]


def signal(b,stop=95,target=120):
    return dict(market=b.market,code=b.code,name=b.name,date=b.date,close=b.close,support=97,stop=stop,target=target,
                score=80,metrics={'average_volume':10000000},reasons=['合成測試用途'])


def once(known,day):
    assert all(not b or b[-1].date<=day for b in known.values())
    return {'candidates':[signal(known[('TWSE','2330')][-1])] if day==dates()[100] else []}


def execute(bs,provider=once,**kwargs):
    return simulate({('TWSE','2330'):bs},NakedParameters(),Execution(max_positions=1),Risk(), 'A',bs[100].date,kwargs.pop('end',bs[-1].date),signal_provider=provider,**kwargs)

class NakedSignalTests(unittest.TestCase):
    def test_three_distinct_price_only_strategies_have_positive_paths(self):
        a=bars(110)
        for i,b in enumerate(a):
            c=100+i*.2+2*math.sin(i*2*math.pi/16);a[i]=replace(b,open=c-.3,high=c+.1,low=c-.5,close=c)
        a[100]=replace(a[100],high=126)
        self.assertIsNotNone(evaluate(a,'A',replace(NakedParameters(),support_tolerance=.04)))
        b=bars(110)
        b=[replace(x,high=105,low=95) for x in b]
        for i in range(95,109):b[i]=replace(b[i],open=105.5,high=106.2,low=105.2,close=106)
        b[95]=replace(b[95],high=107,low=104)
        b[-1]=replace(b[-1],open=105.5,high=107.2,low=105.2,close=107)
        # Wait for a retest; the breakout candle itself is not the entry signal.
        self.assertIsNotNone(evaluate(b,'B',NakedParameters()))
        c=[replace(x,open=110,high=115,low=105,close=110) for x in bars(110)]
        for i in (35,55,75):c[i]=replace(c[i],low=100)
        c[65]=replace(c[65],high=118)
        c[108]=replace(c[108],open=101,high=102,low=100.5,close=101.5)
        c[109]=replace(c[109],open=101.5,high=103.1,low=101,close=103)
        self.assertIsNotNone(evaluate(c,'C',NakedParameters()))
        for model,seq in [('A',a),('B',b),('C',c)]:
            weak=[replace(x,turnover=None) for x in seq]
            self.assertIsNone(evaluate(weak,model,replace(NakedParameters(),support_tolerance=.04)))
        day=b[-1].date;known={('TWSE','2330'):b}
        expected=screen(known,day,'B',NakedParameters())
        known[('TWSE','2330')]=b+[replace(b[-1],date='2099-01-01',close=999,high=999)]
        self.assertEqual(screen(known,day,'B',NakedParameters()),expected)

    def test_invalid_parameters_fail_early(self):
        for kw in ({'minimum_turnover':0},{'max_risk':1},{'pivot_radius':True},{'lookback':20},{'close_location':float('nan')}):
            with self.assertRaises(ValueError):NakedParameters(**kw)
        with self.assertRaises(ValueError):Risk(risk_budget=1)

class NakedExecutionTests(unittest.TestCase):
    def test_next_open_all_costs_and_twentieth_session_exit(self):
        result=execute(bars());t=result['closed_trades'][0]
        self.assertEqual(t['entry_date'],dates()[101]);self.assertEqual(t['exit_date'],dates()[120]);self.assertEqual(t['holding_sessions'],20)
        self.assertEqual(t['entry_price'],fill_price(100,True,Execution()))
        proceeds,fee,tax=sell_proceeds(t['exit_price'],t['quantity'],Execution())
        self.assertAlmostEqual(t['net_pnl'],proceeds-t['cost']);self.assertGreater(result['metrics']['total_costs'],0)
        self.assertLess(result['metrics']['net_return'],0);self.assertAlmostEqual(result['metrics']['return_adding_back_costs'],0)

    def test_ambiguous_same_bar_uses_stop_not_target(self):
        bs=bars();bs[101]=replace(bs[101],high=106,low=97,close=100)
        def p(known,day):return {'candidates':[signal(known[('TWSE','2330')][-1],98,105)] if day==dates()[100] else []}
        result=execute(bs,p);t=result['closed_trades'][0]
        self.assertEqual(t['entry_date'],t['exit_date']);self.assertLess(t['net_pnl'],0);self.assertIn('停損優先',t['exit_reason'])

    def test_gap_stop_executes_lower_open_and_profit_is_not_forced_to_wait(self):
        bs=bars();bs[102]=replace(bs[102],open=94,high=95,low=93,close=94)
        t=execute(bs)['closed_trades'][0];self.assertEqual(t['exit_reason'],'跳空停損');self.assertEqual(t['exit_price'],fill_price(94,False,Execution()))
        bs=bars();bs[102]=replace(bs[102],high=106,low=99.5,close=104)
        def p(known,day):return {'candidates':[signal(known[('TWSE','2330')][-1],98,105)] if day==dates()[100] else []}
        self.assertEqual(execute(bs,p)['closed_trades'][0]['holding_sessions'],2)

    def test_locked_open_defers_without_favorable_fill(self):
        bs=bars();bs[102]=replace(bs[102],open=90,high=90,low=90,close=90,reference=100)
        bs[103]=replace(bs[103],open=91,high=92,low=90.5,close=91,reference=90)
        r=execute(bs);self.assertEqual(r['closed_trades'][0]['exit_date'],dates()[103]);self.assertTrue(r['deferred_exits'])

    def test_missing_terminal_quote_fails_instead_of_hiding_loss(self):
        full=bars();other=[replace(b,market='TPEX',code='6488') for b in full]
        missing=full[:103]
        with self.assertRaisesRegex(DataError,'缺價'):
            simulate({('TWSE','2330'):missing,('TPEX','6488'):other},NakedParameters(),Execution(),Risk(),'A',dates()[100],dates()[110],signal_provider=once)

    def test_future_prices_and_events_do_not_change_earlier_results(self):
        bs=bars();end=bs[105].date
        a=execute(bs,end=end)
        altered=bs[:106]+[replace(b,close=999,high=1000) for b in bs[106:]]
        event=CorporateAction('future','TWSE','2330',bs[110].date,bs[108].date,'split','https://www.twse.com.tw/event',.5,2)
        self.assertEqual(a,execute(altered,end=end,events=[event]))
        with self.assertRaises(ResearchBudgetExceeded):execute(bs,deadline=time.monotonic()-1)

    def test_split_and_dividend_cash_are_not_fake_capital_gains(self):
        bs=bars();effective=bs[103].date
        for i in range(103,len(bs)):bs[i]=replace(bs[i],open=50,high=50.5,low=49.5,close=50,reference=50)
        split=CorporateAction('split','TWSE','2330',effective,bs[100].date,'split','https://www.twse.com.tw/event',.5,2,reference_price=50)
        result=execute(bs,events=[split]);t=result['closed_trades'][0]
        self.assertEqual(t['quantity'],2*t['entry_quantity']);self.assertGreater(t['net_return'],-.05);self.assertLess(t['net_return'],.01)
        # Dividend is an unspendable receivable until payment, even after position closes.
        bs=bars()
        for i in range(103,len(bs)):bs[i]=replace(bs[i],open=99,high=99.5,low=98.5,close=99,reference=99)
        dividend=CorporateAction('dividend','TWSE','2330',effective,bs[100].date,'distribution','https://www.twse.com.tw/event',.99,1,1,99,payable_date=dates(160)[150])
        result=execute(bs,events=[dividend]);self.assertTrue(result['receivables']);self.assertFalse(result['receivables'][0]['paid'])
        self.assertGreater(result['metrics']['net_return'],-.02)
        with self.assertRaisesRegex(DataError,'比率不符'):execute(bs) # Unexplained ex-date reference must stop simulation.

    def test_trailing_stop_becomes_effective_only_after_close(self):
        bs=bars();bs[90]=replace(bs[90],low=98)
        bs[102]=replace(bs[102],open=100,high=110,low=97,close=109.8)
        bs[103]=replace(bs[103],open=100,high=101,low=99,close=100,reference=109.8)
        bs[104]=replace(bs[104],open=100,high=101,low=97,close=99.5,reference=100)
        t=execute(bs)['closed_trades'][0]
        self.assertEqual(t['exit_date'],dates()[104]);self.assertGreater(t['stop'],t['initial_stop'])

    def test_identity_carries_position_and_documented_zero_liquidation_keeps_loss(self):
        bs=bars();other=[replace(b,market='TPEX',code='6488') for b in bs[103:]]
        identity=CorporateAction('transfer','TWSE','2330',bs[103].date,bs[100].date,'identity','https://www.twse.com.tw/event',new_market='TPEX',new_code='6488')
        result=simulate({('TWSE','2330'):bs[:103],('TPEX','6488'):other},NakedParameters(),Execution(max_positions=1),Risk(),'A',bs[100].date,bs[-1].date,[identity],signal_provider=once)
        t=result['closed_trades'][0];self.assertEqual(t['entry_code'],'2330');self.assertEqual(t['code'],'6488')
        event=CorporateAction('liquidation','TWSE','2330',bs[103].date,bs[100].date,'delisting','https://www.twse.com.tw/event',settlement_price=0)
        # Other market quotes preserve the trading calendar after delisting.
        result=simulate({('TWSE','2330'):bs[:103],('TPEX','6488'):other},NakedParameters(),Execution(max_positions=1),Risk(),'A',bs[100].date,bs[-1].date,[event],signal_provider=once)
        self.assertEqual(result['metrics']['losers'],1);self.assertEqual(result['closed_trades'][0]['net_pnl'],-result['closed_trades'][0]['cost'])

    def test_insufficient_open_does_not_buy_lower_rank_with_hindsight(self):
        bs=bars();bs[101]=replace(bs[101],open=110,high=110,close=110,reference=100)
        other=[replace(b,code='6488',market='TPEX',open=100,high=100.5,close=100,reference=100) for b in bs]
        def p(known,day):return {'candidates':[signal(known[k][-1]) for k in [('TWSE','2330'),('TPEX','6488')]] if day==dates()[100] else []}
        r=simulate({('TWSE','2330'):bs,('TPEX','6488'):other},NakedParameters(),Execution(max_positions=1),Risk(),'A',dates()[100],dates()[110],signal_provider=p)
        self.assertEqual(r['metrics']['closed_count'],0);self.assertEqual(r['open_positions'],[])

class PerformanceTests(unittest.TestCase):
    def test_net_monthly_returns_and_winrate_include_all_losses(self):
        curve=[{'date':'2025-01-01','equity':100},{'date':'2025-01-31','equity':110},{'date':'2025-02-28','equity':99}]
        trades=[{'net_pnl':10,'holding_sessions':5},{'net_pnl':-6,'holding_sessions':2},{'net_pnl':-5,'holding_sessions':3}]
        r=metrics(curve,trades,100,3)
        self.assertAlmostEqual(r['win_rate'],1/3);self.assertAlmostEqual(r['expectancy'],-1/3);self.assertAlmostEqual(r['max_drawdown'],.1)
        self.assertAlmostEqual(r['monthly'][1]['net_return'],-.1);self.assertEqual(r['longest_losing_streak'],2)
        self.assertTrue(r['win_rate_wilson_95'][0]<r['win_rate']<r['win_rate_wilson_95'][1])
