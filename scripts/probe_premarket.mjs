import {mkdir,writeFile} from 'node:fs/promises';
import {collect} from '../backend/worker.mjs';
const result=await collect();
await mkdir('.state',{recursive:true});
await writeFile('.state/premarket-source-probe.json',JSON.stringify(result,null,2));
console.log(JSON.stringify({status:result.status,markets:result.markets.map(m=>({symbol:m.symbol,status:m.status,error:m.error})),feeds:result.feeds.map(f=>({source:f.source,status:f.status,error:f.error})),futures:result.futures},null,2));
if(result.status==='error')process.exitCode=1;
