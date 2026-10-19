from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import json,tempfile,time,unittest
from unittest.mock import patch
from screener.validation import Gates,folds,assess,final_once,holdout_reason
from screener.optimizer import research,next_hypothesis
from screener.naked import NakedParameters
from screener.data import Store
from test_naked import bars,dates

class ValidationTests(unittest.TestCase):
    def study(self):return {'analysis_start':dates()[0],'holdout_start':dates(180)[170],'holdout_end':dates(220)[210],'train_sessions':40,'validation_sessions':30,'step_sessions':30,'purge_sessions':20,'embargo_sessions':5,'holdout_status':'pristine','data_start':dates()[0],'as_of':dates(220)[210]}

    def test_walk_forward_purge_embargo_and_reserved_year(self):
        ds=dates(220);s=self.study();plan=folds(ds,s)
        self.assertTrue(plan)
        for f in plan:
            self.assertLess(f['train_entry_cutoff'],f['train_end']);self.assertLess(f['train_end'],f['validation_start']);self.assertLess(f['validation_end'],s['holdout_start'])
            self.assertEqual(ds.index(f['validation_start'])-ds.index(f['train_end'])-1,25)
            self.assertEqual(ds.index(f['train_end'])-ds.index(f['train_entry_cutoff']),20)
        with self.assertRaises(ValueError):folds(ds,{**s,'embargo_sessions':0})

    def fake(self,ret=.05,n=30):
        ts=[{'net_pnl':100 if i%3 else -20,'exit_reason':'盤中結構停損' if i%3==0 else '盤中目標'} for i in range(n)]
        return {'metrics':{'net_return':ret,'closed_count':n,'max_drawdown':.05},'closed_trades':ts,'open_positions':[]}

    def test_winrate_target_is_not_an_acceptance_gate(self):
        r=[self.fake() for _ in range(3)];g=Gates()
        gate=assess(r,[self.fake(.01) for _ in r],[self.fake(.02) for _ in r],g)
        self.assertTrue(gate['passed']);self.assertFalse(gate['target_is_gate'])
        self.assertFalse(assess([self.fake(.05,3)]*3,None,None,g)['passed'])
        self.assertFalse(assess([self.fake(-.01)]*3,None,None,g)['passed'])
        concentrated=[self.fake() for _ in range(3)]
        concentrated[0]['closed_trades'][1]['net_pnl']=100000
        self.assertIn('獲利過度集中一兩筆',assess(concentrated,None,None,g)['reasons'])

    def test_contaminated_test_cannot_be_relabelled_pristine(self):
        s=self.study();ex={'exposures':[{'start':s['holdout_start'],'end':s['holdout_end']}]}
        self.assertIsNotNone(holdout_reason(s,ex))
        with tempfile.TemporaryDirectory() as d:
            called=[];r=final_once(s,ex,{'walk_forward_passed':True},{'status':'ready'},Path(d)/'used',lambda:called.append(1))
            self.assertEqual(r['status'],'blocked');self.assertEqual(called,[])

    def test_final_test_claimed_once_even_if_execution_fails(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.study();f={'walk_forward_passed':True,'frozen_sha256':'abc'};p=Path(d)/'used'
            a=final_once(s,{'exposures':[]},f,{'status':'ready'},p,lambda:{'net_return':.01})
            self.assertEqual(a['status'],'completed')
            b=final_once(s,{'exposures':[]},f,{'status':'ready'},p,lambda:self.fail('must not repeat'))
            self.assertFalse(b['executed'])
            p=Path(d)/'failed'
            def fail():raise RuntimeError('missing quote')
            self.assertEqual(final_once(s,{'exposures':[]},f,{'status':'ready'},p,fail)['status'],'error')
            self.assertFalse(final_once(s,{'exposures':[]},f,{'status':'ready'},p,fail)['executed'])

    def test_single_change_hypothesis_uses_only_first_training_fold(self):
        p=NakedParameters();training=[self.fake(),{'closed_trades':[{'exit_reason':'不可使用後段原因'}]*1000}]
        candidate,field,reason=next_hypothesis(p,training,1)
        self.assertEqual([key for key in asdict(p) if asdict(p)[key]!=asdict(candidate)[key]],[field])
        self.assertNotIn('1000',reason)

    def test_finite_loop_keeps_rejected_trials_and_never_reads_holdout(self):
        cfg=json.loads(Path('naked_k.json').read_text());cfg['study']=self.study();cfg['gates']['minimum_folds']=1;cfg['budget'].update(max_experiments=3,max_seconds=5)
        h={('TWSE','2330'):bars(220)};quality={'status':'ready','research_ready':True,'data_sha256':'fixed'};seen=[]
        class Feed:
            def histories(self,end):
                seen.append(end);return {key:[b for b in bs if b.date<=end] for key,bs in h.items()}
        def ev(hist,p,e,r,model,plan,events,deadline):
            self.assertTrue(all(b.date<cfg['study']['holdout_start'] for bs in hist.values() for b in bs))
            return {'training':[self.fake(-.1)]*len(plan),'validation':[self.fake(-.1)]*len(plan)}
        with tempfile.TemporaryDirectory() as d,patch('screener.optimizer.audit_dataset',return_value=quality),patch('screener.optimizer.actions',return_value=[]):
            out=research(Feed(),cfg,d,evaluator=ev,benchmark_function=lambda *a:self.fake(.01))
            self.assertEqual(len(out['experiments']),3);self.assertEqual({x['model_id'] for x in out['experiments']},{'F'});self.assertTrue(all(not x['retained'] for x in out['experiments']))
            self.assertIsNone(out['active_strategy']);self.assertEqual(len(Path(d,'ledger.jsonl').read_text().splitlines()),3)
            self.assertTrue(all(date<cfg['study']['holdout_start'] for date in seen))
            self.assertFalse(Path(d,'frozen_candidate.json').exists())

    def test_single_strategy_baseline_then_two_single_rule_refinements(self):
        cfg=json.loads(Path('naked_k.json').read_text());cfg['study']=self.study();cfg['gates']['minimum_folds']=1;cfg['budget'].update(max_experiments=9,max_seconds=5)
        h={('TWSE','2330'):bars(220)};quality={'status':'ready','research_ready':True,'data_sha256':'fixed'}
        class Feed:
            def histories(self,end):return {k:[b for b in bs if b.date<=end] for k,bs in h.items()}
        def ev(hist,p,e,r,model,plan,events,deadline):
            ret={'F':.05}[model]+(.01 if p.support_tolerance<.02 else 0)+(.01 if p.close_location>.7 else 0)
            return {'training':[self.fake(ret)]*len(plan),'validation':[self.fake(ret)]*len(plan)}
        with tempfile.TemporaryDirectory() as d,patch('screener.optimizer.audit_dataset',return_value=quality),patch('screener.optimizer.actions',return_value=[]):
            out=research(Feed(),cfg,d,evaluator=ev,benchmark_function=lambda *a:self.fake(.001))
            self.assertEqual([e['model_id'] for e in out['experiments'][:3]],['F','F','F'])
            self.assertEqual(len(out['experiments']),3);self.assertEqual(out['comparison_status'],'complete')
            self.assertEqual(out['frozen_candidate']['model_id'],'F');self.assertIsNone(out['active_strategy'])
            for e in out['experiments'][1:]:
                self.assertEqual(len([k for k in e['parameters'] if e['parameters'][k]!=e['baseline_parameters'][k]]),1)
            self.assertTrue(Path(d,'frozen_candidate.json').exists())

    def test_robustness_failure_rejects_profitable_validation(self):
        cfg=json.loads(Path('naked_k.json').read_text());cfg['study']=self.study();cfg['gates']['minimum_folds']=1;cfg['budget'].update(max_experiments=3,max_seconds=5)
        quality={'status':'ready','research_ready':True,'data_sha256':'fixed'}
        class Feed:
            def histories(self,end):return {('TWSE','2330'):[b for b in bars(220) if b.date<=end]}
        def ev(hist,p,e,r,model,plan,events,deadline):
            ret=-.01 if e.fee_rate>.002 else .05
            return {'training':[self.fake(ret)]*len(plan),'validation':[self.fake(ret)]*len(plan)}
        with tempfile.TemporaryDirectory() as d,patch('screener.optimizer.audit_dataset',return_value=quality),patch('screener.optimizer.actions',return_value=[]):
            out=research(Feed(),cfg,d,evaluator=ev,benchmark_function=lambda *a:self.fake(.001))
            self.assertFalse(any(e['retained'] for e in out['experiments']));self.assertNotIn('frozen_candidate',out)
            self.assertIn('成本或參數微擾不穩健',out['experiments'][0]['assessment']['reasons'])

    def test_data_block_stops_before_fitting_instead_of_zero_return(self):
        cfg=json.loads(Path('naked_k.json').read_text());quality={'status':'blocked','research_ready':False,'data_sha256':'x','issues':['missing data']}
        with tempfile.TemporaryDirectory() as d,patch('screener.optimizer.audit_dataset',return_value=quality):
            out=research(None,cfg,d,evaluator=lambda *a:self.fail('no fitting allowed'))
        self.assertEqual(out['status'],'blocked');self.assertEqual(out['experiments'],[]);self.assertTrue(all(x['metrics'] is None for x in out['candidates']))
