import { createHash, webcrypto } from 'node:crypto';
import { DecompressionStream } from 'node:stream/web';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createLazyReader } from './snapshot-reader.js';
import { snapshotFixture } from '../test/snapshot-fixture.js';

const fields = ['id', 'title', 'venue', 'year', 'publication_date', 'created_at', 'citation_count',
  'directions', 'venue_confirmed', 'doi', 'official_url', 'oa_url', 'first_author', 'authors_count', 'pdf_status', 'pdf_source'];
const flush = async () => { for (let index = 0; index < 20; index++) await Promise.resolve(); };
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; };

beforeEach(() => { vi.stubGlobal('crypto', webcrypto); vi.stubGlobal('DecompressionStream', DecompressionStream); });
afterEach(() => { vi.unstubAllGlobals(); });

function testReader(block) {
  const fixture = snapshotFixture(), values = new Map();
  fixture.papers = Array.from({length:20}, (_, index) => ({...fixture.papers[0], id:index+1, title:`Learning article ${index+1}`}));
  fixture.manifest.paper_count=20;
  const asset = (prefix, rows, metadata={}) => {
    const sha256=createHash('sha256').update(JSON.stringify(rows)).digest('hex');
    const path=`${prefix}-${sha256}.json.gz`;values.set(path,rows);
    return {path,sha256,count:rows.length,...metadata};
  };
  const browse=fixture.papers.map(paper=>asset('browse',[fields.map(field=>paper[field])],{min_id:paper.id,max_id:paper.id}));
  const details=fixture.papers.map(paper=>asset('compressed',[paper],{min_id:paper.id,max_id:paper.id,venues:['AC'],years:[2025],directions:['llm','agent']}));
  fixture.manifest.chunks=details.map(entry=>({path:`papers-${entry.sha256}.json`,sha256:entry.sha256,count:1}));
  const rankingRows=fixture.papers.map(paper=>[1,0,2025,1,1,5,[0,1],0,1]);
  const ranking=asset('ranking',rankingRows,{min_id:1,max_id:20});
  const titles=asset('titles',fixture.papers.map(paper=>[`learning article ${paper.id}`,paper.id]));
  const token='learn',hash=createHash('sha256').update(token).digest('hex').slice(0,3);
  const terms=fixture.papers.map(paper=>asset('search',[[token,paper.id,8,10,[0]]]));
  const descriptor={version:5,paper_count:20,fields,browse,details,browse_chunk_size:1,
    ranking:{version:1,parts:[ranking],venues:['AC'],directions:['llm','agent'],pdf_statuses:['closed']},
    search:{version:3,bucket_chars:3,average_length:10,terms:{[hash]:terms},titles:{},vocabulary:[]}};
  const exactHash=createHash('sha256').update('learning').digest('hex').slice(0,2);descriptor.search.titles[exactHash]=[titles];
  const download=vi.fn(async(path,_digest,_cache,_limit,signal,onProgress)=>{
    await block({path,signal,onProgress});return {data:values.get(path)};
  });
  return {download,reader:createLazyReader({manifest:fixture.manifest,catalog:{...fixture.catalog,reader:descriptor},download})};
}

it('starts sixteen page-card downloads while keeping ordinary term batches at six',async()=>{
  const termGate=deferred(),cardGate=deferred();let terms=0,cards=0,termPeak=0,cardPeak=0;
  const current=testReader(async({path})=>{
    if(path.startsWith('search-')){termPeak=Math.max(termPeak,++terms);await termGate.promise;terms--;}
    if(path.startsWith('browse-')){cardPeak=Math.max(cardPeak,++cards);await cardGate.promise;cards--;}
  });
  const pending=current.reader.call('search',{q:'learning',match:'keywords'});
  try{
    await vi.waitFor(()=>expect(terms).toBe(6));expect(termPeak).toBe(6);termGate.resolve();
    await vi.waitFor(()=>expect(cards).toBe(16));expect(cardPeak).toBe(16);cardGate.resolve();
    const result=await pending;expect(result.total).toBe(20);expect(result.items).toHaveLength(20);
    expect(result.items.map(paper=>paper.id)).toEqual(Array.from({length:20},(_,index)=>20-index));
    expect(termPeak).toBe(6);expect(cardPeak).toBe(16);
  }finally{termGate.resolve();cardGate.resolve();await pending.catch(()=>{});}
});

it('one canceled page does not abort shared card downloads needed by another reader',async()=>{
  const gate=deferred(),signals=[];const current=testReader(async({path,signal})=>{
    if(path.startsWith('browse-')){signals.push(signal);await gate.promise;}
  });
  const controller=new AbortController();
  const first=current.reader.call('papers',{}, {signal:controller.signal});
  const rejected=expect(first).rejects.toMatchObject({name:'AbortError'});
  const second=current.reader.call('papers',{});
  try{
    await vi.waitFor(()=>expect(signals).toHaveLength(16));controller.abort();await rejected;await flush();
    expect(signals.every(signal=>!signal.aborted)).toBe(true);gate.resolve();
    expect((await second).total).toBe(20);
    expect(current.download.mock.calls.filter(([path])=>path.startsWith('browse-'))).toHaveLength(20);
  }finally{controller.abort();gate.resolve();await Promise.allSettled([first,second,rejected]);}
});
