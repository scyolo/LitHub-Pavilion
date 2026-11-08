import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createSnapshotStore } from '../src/data/snapshot-store.js';
import { createLazyReader } from '../src/data/snapshot-reader.js';
import { gunzipSync } from 'node:zlib';
import { decodePostingGroups,unpackDescriptor } from '../src/data/compact-index.js';

const directory=process.env.SNAPSHOT_DIR?pathToFileURL(resolve(process.env.SNAPSHOT_DIR)+'/'):new URL('../static/snapshot/',import.meta.url);
const manifest=JSON.parse(await readFile(new URL('manifest.json',directory)));
const catalog=JSON.parse(await readFile(new URL(manifest.catalog.path,directory)));
assert.ok([6,8,10].includes(catalog.reader.version),'Regenerate the paged reader before this regression');
let paged=JSON.parse(gunzipSync(await readFile(new URL(catalog.reader.index.path,directory))));
if(catalog.reader.version===10)paged=unpackDescriptor(paged);
if(paged.search.lookup) {
  for(const entry of Object.values(paged.search.lookup.parts)) {
    const directory=unpackDescriptor(JSON.parse(gunzipSync(await readFile(new URL(entry.path,process.env.SNAPSHOT_DIR?pathToFileURL(resolve(process.env.SNAPSHOT_DIR)+'/'):new URL('../static/snapshot/',import.meta.url))))));
    Object.assign(paged.search.terms,directory.terms);Object.assign(paged.search.titles,directory.titles);
    Object.assign(paged.search.metadata.terms,directory.metadata);Object.assign(paged.search.hints.terms,directory.hints);
  }
}
// Independent old algorithm: materialize all candidate titles/cards, ignoring
// new title positions and compact ranking rows. This verifies ranking parity
// against the previous production behavior on the same complete dataset.
const legacy=structuredClone(paged);legacy.version=3;legacy.search.version=2;
delete legacy.search.authors;
delete legacy.search.metadata;
delete legacy.search.hints;
delete legacy.search.lookup;
legacy.search.terms={};
for(const [key,entries] of Object.entries(paged.search.terms))(legacy.search.terms[key.slice(0,2)]??=[]).push(...entries);
const reference=createLazyReader({manifest,catalog:{...catalog,reader:legacy},download:async path=>{
  let data=JSON.parse(gunzipSync(await readFile(new URL(path,directory))));
  const storedCount=data.length;
  if(path.startsWith('search-')) {
    data=(paged.search.version >= 5 ? decodePostingGroups(data) : data).map(row=>row.slice(0,4));
    data=Array.from(new Map(data.map(row=>[row[0]+':'+row[1],row])).values());
  }
  return {data,storedCount};
}});
const cases=[['browse', 'papers', {}],['broad-learning','search',{q:'learning'}],['rare-and','search',{q:'speculative decoding'}],['scoped','search',{q:'learning',venue:'ICML',year:2025}],['fuzzy','search',{q:'speculativ decodng'}],['fragments','search',{q:'SpEcUlA DeCoD',match:'fuzzy'}]];
const report={same_corpus_legacy_engine_parity:true,environment:'Node local-file transport; transfer budgets are network-independent, not browser/Internet latency promises',cases:[]};
for(const [name,method,params]of cases){
  let bytes=0;const requests=[];
  const store=createSnapshotStore({baseUrl:'https://reader.example/snapshot/',preferBootstrap:catalog.reader.version===10,fetcher:async(url,options)=>{
    const asset=new URL(url).pathname.slice('/snapshot/'.length);
    assert.ok(/^(manifest\.json|bootstrap\.json\.gz|(?:catalog|reader|browse|ranking|titles|search|vocabulary|matchrank|cardhint|lookup)-[0-9a-f]{64}\.json(?:\.gz)?)$/.test(asset),'Unexpected bulk/detail asset '+asset);
    assert.equal(options.credentials,'omit');
    const content=await readFile(new URL(asset,directory));bytes+=content.byteLength;requests.push(asset);return new Response(content);
  }});
  const start=performance.now(),result=await store.call(method,params),coldMs=Math.round(performance.now()-start),before=requests.length;
  const repeat=performance.now(),again=await store.call(method,params),warmMs=Math.round(performance.now()-repeat);
  const expected=await reference.call(method,params);
  assert.deepEqual(result,expected,'Paged versus materialized engine mismatch: '+name);
  assert.equal(result.total,again.total);assert.deepEqual(result.items,again.items);assert.equal(requests.length,before,'Warm repeat must reuse verified assets');
  const cards=requests.filter(p=>p.startsWith('browse-')).length;
  const rankShards=requests.filter(p=>p.startsWith('ranking-')).length;
  if(method==='search'&&result.total)assert.ok(rankShards>0||requests.some(path=>path.startsWith('matchrank-')),'Load verified candidate ranking metadata: '+name);
  assert.ok(cards<=result.items.length,'Must not download cards for off-page results');
  assert.ok(bytes<=3*1024*1024,'Cold read exceeded 3 MiB: '+name+' '+bytes);
  assert.ok(requests.length<=40,'Cold read fanout exceeded 40: '+name);
  assert.ok(coldMs<6000,'Local cold processing exceeded 6s: '+name);
  assert.ok(warmMs<1500,'Local warm processing exceeded 1.5s: '+name);
  report.cases.push({name,total:result.total,items:result.items.length,body_bytes:bytes,requests:requests.length,card_shards:cards,ranking_shards:rankShards,cold_ms:coldMs,warm_ms:warmMs});
}
if(process.argv[2]){await mkdir(dirname(resolve(process.argv[2])),{recursive:true});await writeFile(process.argv[2],JSON.stringify(report,null,2));}
console.log(JSON.stringify(report,null,2));
