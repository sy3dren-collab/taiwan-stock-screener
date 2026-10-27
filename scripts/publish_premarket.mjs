// GitHub-hosted backup: real source collection, not a replacement for a live Worker.
import {mkdir,writeFile} from 'node:fs/promises';
import {collect} from '../backend/worker.mjs';
const result=await collect();
await mkdir('site/premarket-runs',{recursive:true});
const body=JSON.stringify(result,null,2)+'\n';
await writeFile('site/premarket.json',body);
await writeFile('site/premarket-runs/'+new Date().toISOString().replace(/[:.]/g,'')+'.json',body);
console.log(JSON.stringify({status:result.status,generated_at:result.generated_at,
  healthy_quotes:result.markets.filter(m=>m.status==='ok').length,
  futures_status:result.futures.status,news:Object.fromEntries(Object.entries(result.news).map(([k,v])=>[k,v.length]))}));
if(result.status!=='ok')process.exitCode=1;
