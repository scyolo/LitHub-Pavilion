import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createSnapshotStore } from '../src/data/snapshot-store.js';
import { authorTokens, matchingAuthors, compareAuthorNames, normalizeAuthorName } from '../src/data/author-search.js';
import { publicationSortKey } from '../src/lib/presentation.js';

const directory=process.env.SNAPSHOT_DIR?pathToFileURL(resolve(process.env.SNAPSHOT_DIR)+'/'):new URL('../static/snapshot/',import.meta.url);
const manifest=JSON.parse(await readFile(new URL('manifest.json',directory)));
const papers=[];
for(const entry of manifest.chunks) papers.push(...JSON.parse(await readFile(new URL(entry.path,directory))));
const catalog=JSON.parse(await readFile(new URL(manifest.catalog.path,directory)));
assert.ok([8,10].includes(catalog.reader.version),'Regenerate the snapshot author index before checking author recall');
const cases=[['full-name',{q:'Yoshua Bengio'}],['reversed-name',{q:'BENGIO YOSHUA'}],
  ['wide-name',{q:'Ｙｏｓｈｕａ Ｂｅｎｇｉｏ'}],['common-surname',{q:'Wang'}],
  ['scoped-name',{q:'Yoshua Bengio',year:2025,venue:'NeurIPS'}]];
const samples=[];
for(const paper of papers) {
  const name=paper.authors.find(author=>/[^\x20-\x7e]/u.test(author.name))?.name;
  if(name && !samples.includes(name))samples.push(name);
  if(samples.length===3)break;
}
cases.push(...samples.map((q,i)=>['unicode-'+i,{q}]));
const report={paper_count:manifest.paper_count,revision:manifest.revision,cases:[],environment:'Node; real public authorship records; local-file transport; no Internet latency claim'};
for(const [name,params] of cases) {
  const tokens=new Set(authorTokens(params.q));
  const expected=papers.filter(paper=>(!params.year||paper.year===params.year)&&(!params.venue||paper.venue===params.venue)
    &&paper.authors.some(author=>tokens.size&&[...tokens].every(token=>new Set(normalizeAuthorName(author.name).split(' ')).has(token))))
    .sort((a,b)=>publicationSortKey(b).localeCompare(publicationSortKey(a))||b.id-a.id);
  const requests=[];let bytes=0;
  const store=createSnapshotStore({baseUrl:'https://reader.example/snapshot/',preferBootstrap:catalog.reader.version===10,fetcher:async(url,options)=>{
    const asset=new URL(url).pathname.slice('/snapshot/'.length);
    assert.ok(/^(manifest\.json|bootstrap\.json\.gz|(?:catalog|reader|authors|author|ranking|browse)-[0-9a-f]{64}\.json(?:\.gz)?)$/.test(asset),'Unexpected detail/title/keyword asset: '+asset);
    assert.equal(options.credentials,'omit');const content=await readFile(new URL(asset,directory));
    requests.push(asset);bytes+=content.byteLength;return new Response(content);
  }});
  const started=performance.now();const result=await store.call('search',{...params,match:'author'});
  const cold=Math.round(performance.now()-started),before=requests.length,repeat=performance.now();
  assert.deepEqual(await store.call('search',{...params,match:'author'}),result);
  const warm=Math.round(performance.now()-repeat);
  assert.equal(result.total,expected.length,name);assert.equal(result.match_mode,'author');assert.equal(result.effective_sort,'publication_desc');
  assert.deepEqual(result.items.map(p=>p.id),expected.slice(0,20).map(p=>p.id));
  for(const item of result.items) {
    assert.equal(item.score,0);
    const paper=expected.find(p=>p.id===item.id);
    assert.deepEqual(item.matched_authors,matchingAuthors(paper.authors,params.q).sort(compareAuthorNames));
  }
  assert.equal(requests.length,before,'Warm search must reuse verified author assets');
  assert.ok(bytes<=3*1024*1024,'Author search exceeded 3 MiB');assert.ok(requests.length<=40,'Author search exceeded 40 requests');
  assert.ok(cold<6000,'Author cold processing exceeded 6s');assert.ok(warm<1500,'Author warm processing exceeded 1.5s');
  const row={name,query:params.q,total:result.total,cold_ms:cold,warm_ms:warm,bytes,requests:requests.length};
  report.cases.push(row);console.log(JSON.stringify(row));
}
report.passed=true;
if(process.argv[2]){await mkdir(dirname(resolve(process.argv[2])),{recursive:true});await writeFile(process.argv[2],JSON.stringify(report,null,2));}
