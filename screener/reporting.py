"""Immutable per-invocation results, including blocked and failed attempts; no messaging service."""
from datetime import datetime,timezone
import json,re,uuid
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from .__main__ import write_json
from .fusion import MODEL_ID,MODEL_NAME


def trial_summary(record):
    annual=record.get('results',{}).get('annual')
    reports=[annual] if annual else record.get('results',{}).get('validation',[])
    trades=[t for r in reports for t in r.get('closed_trades',[])]
    profit=sum(max(0,t['net_pnl']) for t in trades);loss=-sum(min(0,t['net_pnl']) for t in trades)
    return {'experiment_id':record['experiment_id'],'iteration':record.get('iteration'),
            'status':record['status'],'changed_rules':record.get('changed_rules',[]),'reason':record.get('reason'),
            'retained':bool(record.get('retained')),'passed':bool(record.get('assessment',{}).get('passed')),
            'closed_count':len(trades) if reports else None,'win_rate':sum(t['net_pnl']>0 for t in trades)/len(trades) if trades else None,
            'mean_validation_return':mean(r['metrics']['net_return'] for r in reports) if reports and not annual else None,
            'annual_net_return':annual['metrics']['net_return'] if annual else None,
            'report_kind':'annual_diagnostic' if annual else 'walk_forward',
            'max_fold_drawdown':max(r['metrics']['max_drawdown'] for r in reports) if reports else None,
            'profit_factor':profit/loss if loss else None,'expectancy':mean(t['net_pnl'] for t in trades) if trades else None,
            'total_validation_costs':sum(r['metrics'].get('total_costs',0) for r in reports) if reports else None,
            'error':record.get('error'),'rejection_reasons':record.get('assessment',{}).get('reasons',[])}


def markdown(run):
    pct=lambda value:'—' if value is None else f'{value:.2%}'
    clean=lambda text:str(text).replace('|','／').replace('\n',' ')
    displayed_time=datetime.fromisoformat(run['generated_at']).astimezone(ZoneInfo('Asia/Taipei')).isoformat()
    annual=run['command']=='annual-research'
    rows=[f"## 每次回測報告｜{MODEL_NAME}",f"- 執行：{run['run_id']}（{displayed_time}，台北）",
          f"- 狀態：{run['status']}；有效實驗 {run['completed_experiments']} 次；正式策略未因研究自動啟用。",
          '- 85%為長期研究目標，不是晉級門檻。'+('本輪為一年連續帳戶回溯研究，不能用於正式晉級。' if annual else '各驗證折重設現金，平均報酬不是連續帳戶年報酬。'),
          '', f"| 輪次 | 勝率 | 已平倉 | {'一年帳戶淨報酬' if annual else '跨折平均淨報酬'} | {'最大回撤' if annual else '最大單折回撤'} | 保留 |", '| --- | ---: | ---: | ---: | ---: | --- |']
    for t in run['trials']:rows.append(f"| {t['iteration']} | {pct(t['win_rate'])} | {t['closed_count'] if t['closed_count'] is not None else '—'} | {pct(t.get('annual_net_return') if annual else t['mean_validation_return'])} | {pct(t['max_fold_drawdown'])} | {'是' if t['retained'] else '否'} |")
    if not run['trials']:rows.append('| 未執行有效回測 | — | — | — | — | 否 |')
    rows+=['',*[f'- {clean(issue)}' for issue in run['issues']]]
    for t in run['trials']:rows.append(f"- {t['experiment_id']}：{clean(t['reason'])}；{clean(t['error'] or '；'.join(t['rejection_reasons']) or t['status'])}")
    rows+=['',f"- 程式版本：{run.get('version',{}).get('git_commit','未取得')}；資料指紋：{run.get('data_sha256') or '未取得'}",
           '- 本報告包含失敗及資料不足，不以缺資料填0%或宣稱達到85%。']
    return '\n'.join(rows)+'\n'


def export_history(state_dir,site_dir):
    state,site=Path(state_dir),Path(site_dir);site.mkdir(parents=True,exist_ok=True)
    ledger=state/'ledger.jsonl';runs=[json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    runs=[r for r in runs if r.get('model_id')==MODEL_ID]
    visible=list(reversed(runs[-200:]));published=site/'runs';published.mkdir(exist_ok=True)
    keep={r['run_id'] for r in visible[:20]}
    for run in visible:
        name=run['run_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('回測紀錄識別碼不合法')
        run['download_url']=f'runs/{name}.json' if name in keep else None
        if name in keep:write_json(published/f'{name}.json',json.loads((state/f'{name}.json').read_text()))
    for old in published.glob('*.json'):
        if old.stem not in keep:old.unlink()
    write_json(site/'research-history.json',{'schema_version':1,'model_id':MODEL_ID,'runs':visible,'total_runs':len(runs)})
    if visible:(site/'latest-backtest.md').write_text(markdown(visible[0]))
    return visible


def record_run(result,command,experiment_dir,state_dir='.state/runs',site_dir='site',summary_path=None):
    now=datetime.now(timezone.utc);identifier=f'{now:%Y%m%dT%H%M%S%f}-{MODEL_ID}-{command}-{uuid.uuid4().hex[:8]}'
    state=Path(state_dir);state.mkdir(parents=True,exist_ok=True)
    expanded=[]
    final=result.get('result',{}).get('strategy')
    if command=='annual-research' and result.get('status')=='completed' and result.get('strategy'):
        expanded.append({'experiment_id':identifier+'-annual','iteration':'一年回溯基準','status':'completed',
                         'reason':'固定合併策略完整一年研究回測，非獨立樣本外；不凍結、不晉級',
                         'retained':False,'results':{'annual':result['strategy']},'assessment':{'passed':False,'reasons':['一年已被研究使用，僅供診斷；未通過五年與獨立驗證']}})
    if command=='final-test' and result.get('executed') and final:
        expanded.append({'experiment_id':identifier+'-final','iteration':'封存測試','status':result['status'],
                         'reason':'凍結後的一次性封存測試，不用於調參','retained':False,
                         'results':{'validation':[final]},'assessment':result.get('result',{}).get('assessment',{})})
    for item in result.get('experiments',[]):
        name=item['experiment_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('實驗識別碼不合法')
        path=Path(experiment_dir)/f'{name}.json'
        expanded.append(json.loads(path.read_text()) if path.exists() else item)
    issues=result.get('data_quality',{}).get('issues',[])[:]
    if command=='annual-research':issues+=result.get('data_quality',{}).get('limitations',[])
    for issue in [result.get('reason'),result.get('run_error')]:
        if issue and issue not in issues:issues.append(issue)
    run={'schema_version':1,'run_id':identifier,'generated_at':now.isoformat(),'model_id':MODEL_ID,'model_name':MODEL_NAME,
         'command':command,'status':result.get('status','error'),'stop_reason':result.get('stop_reason'),
         'completed_experiments':sum(r['status']=='completed' for r in expanded),'version':result.get('version',{}),
         'data_sha256':result.get('training_data_quality',result.get('data_quality',{})).get('data_sha256'),
         'issues':issues,'trials':[trial_summary(r) for r in expanded]}
    # Every invocation is a separate immutable snapshot, including blocked/error outcomes.
    write_json(state/f'{identifier}.json',{**run,'report':result,'trial_reports':expanded})
    with (state/'ledger.jsonl').open('a') as stream:stream.write(json.dumps(run,ensure_ascii=False,allow_nan=False)+'\n')
    export_history(state,site_dir)
    content=markdown(run);(Path(site_dir)/'latest-backtest.md').write_text(content)
    summary=summary_path
    if summary:
        with Path(summary).open('a') as stream:stream.write(content)
    return run


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='由持久回測帳本輸出網站紀錄，不執行新回測')
    parser.add_argument('command',choices=['export']);parser.add_argument('--state',default='.state/runs');parser.add_argument('--site',default='site')
    args=parser.parse_args();export_history(args.state,args.site)
