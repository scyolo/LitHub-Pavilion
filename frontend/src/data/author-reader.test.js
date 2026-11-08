import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { gunzipSync } from 'node:zlib';
import { webcrypto } from 'node:crypto';
import { DecompressionStream } from 'node:stream/web';
import { afterAll, beforeAll, expect, it, vi } from 'vitest';
import { snapshotFixture } from '../test/snapshot-fixture.js';
import { createSnapshotEngine } from './snapshot-engine.js';
import { createLazyReader } from './snapshot-reader.js';

const fixture = snapshotFixture();
const names = [['First Writer', 'Bengio, Yoshua', 'José García', '王小明'], ['Yoshua Smith', 'Sam Bengio'], ['Yoshua Bengio', 'Bengio, Yoshua']];
fixture.papers.forEach((paper, index) => {
  paper.authors = names[index].map((name, order) => ({name, order:order+1}));
  paper.first_author = names[index][0]; paper.authors_count = names[index].length;
  paper.authors_preview = names[index].slice(0,3);
});
let directory, descriptor, legacy, manifest;
beforeAll(() => {
  vi.stubGlobal('crypto', webcrypto); vi.stubGlobal('DecompressionStream', DecompressionStream);
  directory = mkdtempSync(join(tmpdir(), 'author-reader-'));
  const local=resolve('../backend/.venv/Scripts/python.exe'), unix=resolve('../backend/.venv/bin/python');
  const python=existsSync(local)?local:existsSync(unix)?unix:'python';
  const script = `
import json,sys
from pathlib import Path
from app.services.snapshot import _write_content,_json_bytes
from app.services.snapshot_reader import build_reader_assets,load_reader_descriptor
fixture=json.load(sys.stdin);directory=Path(sys.argv[1]);chunks=[]
for paper in fixture['papers']:
 chunks.append(dict(_write_content(directory,'papers',_json_bytes([paper])),count=1))
manifest=dict(fixture['manifest'],chunks=chunks)
print(json.dumps(dict(manifest=manifest,reader=build_reader_assets(directory,manifest,version=8),legacy=build_reader_assets(directory,manifest,version=6))))
`;
  const data=JSON.parse(execFileSync(python,['-c',script,directory],{encoding:'utf8',input:JSON.stringify(fixture),env:{...process.env,PYTHONPATH:resolve('../backend'),PYTHONIOENCODING:'utf-8'}}));
  ({manifest,reader:descriptor,legacy}=data);
}, 30000);
afterAll(() => {vi.unstubAllGlobals();if(directory)rmSync(directory,{recursive:true,force:true});});
function reader(selected=descriptor) {
  const download=vi.fn(async path=>({data:JSON.parse(gunzipSync(readFileSync(join(directory,path))))}));
  return {download,reader:createLazyReader({manifest,catalog:{...fixture.catalog,reader:selected},download})};
}
it.each(['Yoshua Bengio','BENGIO YOSHUA','Ｂｅｎｇｉｏ Ｙｏｓｈｕａ','José García','garcia jose','王小明','Bengio'])(
  'matches every authorship slot, with same-author AND and stable pages: %s', async q => {
    const current=reader(),full=createSnapshotEngine(fixture);
    for(const params of [{q,match:'author'},{q,match:'author',size:1,page:2},{q,match:'author',size:1,page:5},
      {q,match:'author',year:2025},{q,match:'author',venue:'BJ'},{q,match:'author',direction:'agent'},
      {q,match:'author',sort:'citation_desc'}]) {
      const actual=await current.reader.call('search',params),expected=full.search(params);
      expect(actual.total).toBe(expected.total);
      expect(actual.match_mode).toBe('author');
      expect(actual.effective_sort).toBe(expected.effective_sort);
      expect(actual.items.map(({id,score,matched_authors})=>({id,score,matched_authors}))).toEqual(
        expected.items.map(({id,score,matched_authors})=>({id,score,matched_authors})));
    }
    expect(current.download.mock.calls.every(([path])=>/^(reader|authors|author|ranking|browse)-/.test(path))).toBe(true);
  }
);
it('does not match different coauthors or prefixes, and reuses the index on repeated query', async()=>{
  const current=reader();
  const actual=await current.reader.call('search',{q:'Yoshua Bengio',match:'author'});
  expect(actual.items.map(p=>p.id)).toEqual([35,11]);
  const calls=current.download.mock.calls.length;
  expect(await current.reader.call('search',{q:'Bengio Yoshua',match:'author'})).toEqual(actual);
  expect(current.download).toHaveBeenCalledTimes(calls);
  expect((await current.reader.call('search',{q:'Bengi',match:'author'})).total).toBe(0);
});
it('keeps old snapshot keyword searches working and clearly reports missing author indexes',async()=>{
  const current=reader(legacy);
  expect((await current.reader.call('search',{q:'model'})).total).toBe(3);
  const before=current.download.mock.calls.length;
  await expect(current.reader.call('search',{q:'Bengio',match:'author'})).rejects.toMatchObject({code:'AUTHOR_INDEX_UNAVAILABLE'});
  expect(current.download).toHaveBeenCalledTimes(before);
});
it.each(['','!!!','name '.repeat(13),'x'.repeat(201)])('rejects invalid author input without fetching author assets: %s',async q=>{
  const current=reader();
  await expect(current.reader.call('search',{q,match:'author'})).rejects.toMatchObject({status:400});
  expect(current.download.mock.calls.every(([path])=>path.startsWith('reader-'))).toBe(true);
});

it('keeps keyword and author query caches separate for identical input',async()=>{
  const current=reader();
  expect((await current.reader.call('search',{q:'Bengio',match:'author'})).total).toBe(3);
  expect((await current.reader.call('search',{q:'Bengio',match:'keywords'})).total).toBe(0);
  expect((await current.reader.call('search',{q:'Bengio',match:'author'})).total).toBe(3);
});

it('removes one canceled reader while sharing author-directory transfer with another',async()=>{
  const cancel=new AbortController();let unblock,loading;
  const ready=new Promise(resolve=>{unblock=resolve;});
  const download=vi.fn(async(path,_digest,_cache,_limit,signal,onProgress)=>{
    if(path.startsWith('authors-')) {loading={signal,onProgress};await ready;}
    return {data:JSON.parse(gunzipSync(readFileSync(join(directory,path))))};
  });
  const current=createLazyReader({manifest,catalog:{...fixture.catalog,reader:descriptor},download});
  const first=current.call('search',{q:'Yoshua Bengio',match:'author'},{signal:cancel.signal});
  const rejected=expect(first).rejects.toMatchObject({name:'AbortError'});
  const progress=vi.fn();const second=current.call('search',{q:'Bengio',match:'author'},{onProgress:progress});
  await vi.waitFor(()=>expect(loading).toBeDefined());
  cancel.abort();await rejected;
  expect(loading.signal.aborted).toBe(false);loading.onProgress({bytes:100});
  expect(progress).toHaveBeenCalledWith({bytes:100});unblock();
  expect((await second).total).toBe(3);
  expect(download.mock.calls.filter(([path])=>path.startsWith('authors-'))).toHaveLength(1);
});

it('validates author directory paths before author-posting downloads',async()=>{
  const download=vi.fn(async path=>{
    const data=JSON.parse(gunzipSync(readFileSync(join(directory,path))));
    if(path.startsWith('authors-'))Object.values(data.terms)[0][0].path='../escape.json.gz';
    return {data};
  });
  const current=createLazyReader({manifest,catalog:{...fixture.catalog,reader:descriptor},download});
  await expect(current.call('search',{q:'Bengio',match:'author'})).rejects.toMatchObject({code:'INVALID_SNAPSHOT'});
  expect(download.mock.calls.some(([path])=>path.startsWith('author-'))).toBe(false);
});
