# One-off instrumentation for rejection counts only, never portfolio results.
import ast,inspect,json,hashlib,time
from collections import Counter
from pathlib import Path
from bisect import bisect_right
from screener import naked,fusion
from screener.annual import GuardedSignals
from screener.data import Store
from screener.quality import actions
counts=Counter();source_lines={}
def reject(label):counts[label]+=1;return None
class TraceReturns(ast.NodeTransformer):
 def __init__(self,label,offset,lines):self.label=label;self.offset=offset;self.lines=lines
 def visit_Return(self,node):
  if isinstance(node.value,ast.Constant) and node.value.value is None:
   label=f'{self.label}:{self.offset+node.lineno-1}';source_lines[label]=self.lines[node.lineno-1].strip()
   node.value=ast.Call(func=ast.Name(id='__reject_none',ctx=ast.Load()),args=[ast.Constant(label)],keywords=[])
  return node

def traced(fn,overrides={}):
 lines,offset=inspect.getsourcelines(fn);source=''.join(lines);tree=TraceReturns(fn.__name__,offset,lines).visit(ast.parse(source));ast.fix_missing_locations(tree)
 namespace={**fn.__globals__,**overrides,'__reject_none':reject};exec(compile(tree,'<rejection-counts-only>','exec'),namespace);return namespace[fn.__name__]
pattern=traced(fusion.pattern);evaluation=traced(naked.evaluate,{'fusion_pattern':pattern})
# Check behavioral identity on explicit synthetic fixtures, never saved as prices.
import sys
sys.path.insert(0,'tests');from test_fusion import fusion_bars
p=naked.NakedParameters(**json.load(open('naked_k.json'))['signal']);test=fusion_bars()
for n in range(100,156):assert evaluation(test[:n],'F',p)==naked.evaluate(test[:n],'F',p)
counts.clear();naked.evaluate=evaluation
s=Store('.state/annual.sqlite3');hist={k:[b for b in bs if b.date>='2025-04-01'] for k,bs in s.histories('2026-10-16').items()}
hist={k:v for k,v in hist.items() if v};events=actions(s);barriers=[json.loads(r[0]) for r in s.db.execute('select payload from distribution_rows') if not json.loads(r[0])['supported']];s.close()
all_days=sorted({b.date for bs in hist.values() for b in bs});index={k:[b.date for b in bs] for k,bs in hist.items()};baseline=json.load(open('site/annual-backtest.json'));provider=GuardedSignals(p,events,all_days,barriers)
for day in all_days:
 if not '2025-10-17'<=day<=baseline['entry_cutoff']:continue
 known={}
 for k,bs in hist.items():
  i=bisect_right(index[k],day);known[k]=bs[max(0,i-p.lookback-1):i]
 provider(known,day)
result={'classification':'rejection_counts_only_not_a_backtest','counts':dict(counts),'source_lines':source_lines,'funnel':dict(provider.counts),'original_code_version':baseline['version'],'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
Path('/tmp/fusion-rejection-counts.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False))
