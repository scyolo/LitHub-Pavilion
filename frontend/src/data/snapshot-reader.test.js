import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, join } from "node:path";
import { gunzipSync } from "node:zlib";
import { createHash, webcrypto } from "node:crypto";
import { DecompressionStream } from "node:stream/web";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import { snapshotFixture } from "../test/snapshot-fixture.js";
import { createSnapshotEngine } from "./snapshot-engine.js";
import { createLazyReader } from "./snapshot-reader.js";

const fixture = snapshotFixture();
fixture.papers.push({ ...fixture.papers[0], id: 57, title: "Unicode α and 𝔹 mathematics " + "retrieval ".repeat(35) });
fixture.papers.push({ ...fixture.papers[1], id: 69, title: "Other title", abstract: "Onlyabstract matching retrieval" });
fixture.papers[0].abstract += " FlashAttention-2";
fixture.papers[1].abstract += " FlashAttention2";
fixture.manifest.paper_count = fixture.papers.length;
let directory, data;

beforeAll(() => {
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("DecompressionStream", DecompressionStream);
  directory = mkdtempSync(join(tmpdir(), "reader-test-"));
  const local = resolve("../backend/.venv/Scripts/python.exe");
  const unix = resolve("../backend/.venv/bin/python");
  const python = existsSync(local) ? local : existsSync(unix) ? unix : "python";
  const script = `
import sys,json
from pathlib import Path
from app.services.snapshot import _write_content,_json_bytes
from app.services.snapshot_reader import build_reader_assets, load_reader_descriptor
fixture=json.load(sys.stdin)
directory=Path(sys.argv[1])
chunks=[]
for row in fixture['papers']:
    chunks.append(dict(_write_content(directory,'papers',_json_bytes([row])),count=1))
manifest=dict(fixture['manifest'],chunks=chunks)
print(json.dumps(dict(manifest=manifest,reader=build_reader_assets(directory,manifest),paged=load_reader_descriptor(directory,{"reader":build_reader_assets(directory,manifest,version=6)}))))
`;
  data = JSON.parse(execFileSync(python, ["-c", script, directory], { encoding: "utf8", input: JSON.stringify(fixture), env: { ...process.env, PYTHONPATH: resolve("../backend"), PYTHONIOENCODING: "utf-8" } }));
}, 30000);
afterAll(() => { vi.unstubAllGlobals(); if (directory) rmSync(directory, { recursive: true, force: true }); });

function reader() {
  const download = vi.fn(async (path) => ({ data: JSON.parse(gunzipSync(readFileSync(join(directory, path)))) }));
  return { download, reader: createLazyReader({ manifest: data.manifest, catalog: { ...fixture.catalog, reader: data.reader }, download }) };
}

it('retains journal rows through range pruning for an opted-in conference source', async () => {
  const catalog = {...fixture.catalog, conference_associations: {AC: {'2025': [23], '2026': [23]}}};
  const full = createSnapshotEngine({...fixture, catalog});
  for (const descriptor of [data.reader, data.paged]) {
    const download = vi.fn(async path => ({data: JSON.parse(gunzipSync(readFileSync(join(directory, path))))}));
    const current = createLazyReader({manifest: data.manifest, catalog: {...catalog, reader: descriptor}, download});
    for (const params of [
      {q: 'Agents in planning', match: 'exact', venue: 'AC', level: 'A', type: 'conf', year: 2024, include_associated: '1'},
      {q: 'model', venue: 'AC', type: 'conf', include_associated: true, direction: 'agent'},
      {q: 'Agents in planning', venue: 'AC', include_associated: true, year: 2025},
      {q: 'Agents in planning', venue: 'AC'},
    ]) {
      const actual = await current.call('search', params), expected = full.search(params);
      expect(actual.total).toBe(expected.total);
      expect(actual.items.map(p => p.id)).toEqual(expected.items.map(p => p.id));
    }
    expect((await current.call('papers', {venue: 'AC', level: 'A', type: 'conf', year: 2024, include_associated: '1'})).items.map(p => p.id)).toEqual([23]);
  }
});

it('prefers the known method spelling, retaining literal mode and scoped fallback', async () => {
  for (const create of [reader, pagedReader]) {
    const current=create();
    const canonical=await current.reader.call('search',{q:'FlashAttention2'});
    expect(canonical.items.map(p=>p.id)).toEqual([11]);
    expect(canonical.query_rewrite).toBe('FlashAttention 2');
    const expected=createSnapshotEngine(fixture).search({q:'FlashAttention2'});
    expect(canonical.total).toBe(expected.total);
    expect(canonical.items.map(({id,score})=>({id,score}))).toEqual(expected.items.map(({id,score})=>({id,score})));
    const literal=await current.reader.call('search',{q:'FlashAttention2',match:'keywords'});
    expect(literal.items.map(p=>p.id)).toEqual([23]);
    const scoped=await current.reader.call('search',{q:'FlashAttention2',year:2024});
    expect(scoped.items.map(p=>p.id)).toEqual([23]);
    expect(scoped.query_rewrite).toBeUndefined();
  }
});

it("resolves Chinese topics consistently without loading text postings in the paged reader", async () => {
  for (const create of [reader, pagedReader]) {
    const current=create();
    const result=await current.reader.call('search',{q:'大模型',direction:'agent',size:1});
    const expected=fixture.papers.filter(p=>p.directions.includes('llm')&&p.directions.includes('agent'));
    expect(result.total).toBe(expected.length);
    expect(result.match_mode).toBe('topic');
    expect(result.items).toHaveLength(1);
    if(create===pagedReader)expect(current.download.mock.calls.some(([path])=>path.startsWith('search-')||path.startsWith('vocabulary-'))).toBe(false);
  }
});

it("matches the full engine for AND, stemming, abstract, exact title, filters and pagination without details", async () => {
  const current = reader();
  const full = createSnapshotEngine(fixture);
  for (const params of [
    { q: "model decoding" }, { q: "accelerated inference" }, { q: "onlyabstract" },
    ...fixture.papers.map((paper) => ({ q: paper.title })),
    { q: "model", level: "A", year: 2025 }, { q: "model", direction: "agent" },
    { q: "retrieval", sort: "citation_desc", page: 2, size: 1 }, { q: "absenttermxyz" },
  ]) {
    const result = await current.reader.call("search", params);
    const expected = full.search(params);
    expect(result.total).toBe(expected.total);
    expect(result.items.map(({ id, score }) => ({ id, score }))).toEqual(expected.items.map(({ id, score }) => ({ id, score })));
  }
  expect(current.download.mock.calls.every(([path]) => !path.startsWith("compressed-") && !path.startsWith("papers-"))).toBe(true);
});

it("fetches a single exact detail chunk only when opening a paper", async () => {
  const current = reader();
  const detail = await current.reader.call("paper", 23);
  expect(detail.abstract).toBe(fixture.papers[1].abstract);
  expect(current.download).toHaveBeenCalledTimes(1);
  expect(current.download.mock.calls[0][0]).toMatch(/^compressed-/);
});

it("rejects unsafe shard paths before any download", () => {
  const descriptor = structuredClone(data.reader);
  Object.values(descriptor.search.terms)[0][0].path = "../escape.json.gz";
  expect(() => createLazyReader({ manifest: data.manifest, catalog: { ...fixture.catalog, reader: descriptor }, download: vi.fn() })).toThrow();
});

it("supports exact, typo and prefix retrieval in both overlapping directions without loading details", async () => {
  const current = reader();
  for (const match of ['auto', 'fuzzy']) for (const direction of ['llm', 'agent', 'llm,agent']) {
    const result = await current.reader.call('search', { q: 'spceulative dec', direction, match });
    expect(result.items.some(row => row.id === 11)).toBe(true);
    expect(new Set(result.items.map(row => row.id)).size).toBe(result.items.length);
    expect(result.match_mode).toBe('fuzzy');
  }
  const exact = await current.reader.call('search', { q: fixture.papers[0].title.toUpperCase(), match: 'exact' });
  expect(exact.items.map(row => row.id)).toEqual([11]);
  expect((await current.reader.call('search', { q: 'speculative decoding', match: 'exact' })).total).toBe(0);
  expect((await current.reader.call('search', { q: 'spceulative dec', match: 'fuzzy', year: 2001 })).total).toBe(0);
  expect(current.download.mock.calls.every(([path]) => !path.startsWith('compressed-') && !path.startsWith('papers-'))).toBe(true);
});

it("an exact title request reads no keyword, vocabulary or full detail shards", async () => {
  const current = reader();
  const result = await current.reader.call('search', { q: fixture.papers[0].title, match: 'exact' });
  expect(result.items[0].id).toBe(11);
  expect(current.download.mock.calls.every(([path]) => /^(titles|browse)-/.test(path))).toBe(true);
});

it.each(['speculativ decoding', 'speculativ decoding decoding', 'spceulative decoding', 'decding'])("corrects raw-word typos before stemming: %s", async (q) => {
  const current = reader();
  const full = createSnapshotEngine(fixture);
  for (const match of ['auto', 'fuzzy']) {
    const result = await current.reader.call('search', { q, match, direction: 'llm' });
    expect(result.items.some(row => row.id === 11)).toBe(true);
    expect(full.search({ q, match, direction: 'llm' }).items.some(row => row.id === 11)).toBe(true);
  }
});


it("scoped browsing reads only overlapping card shards and preserves exact totals and pagination", async () => {
  const descriptor = structuredClone(data.reader);
  const values = new Map();
  descriptor.browse = fixture.papers.map(paper => {
    const rows = [descriptor.fields.map(field => paper[field])];
    const sha256 = createHash("sha256").update(JSON.stringify(rows)).digest("hex");
    const path = `browse-${sha256}.json.gz`;
    values.set(path, rows);
    return { path, sha256, count: 1, min_id: paper.id, max_id: paper.id };
  });
  const full = createSnapshotEngine(fixture);
  for (const params of [{ venue: "BJ" }, { venue: "AC", size: 1, page: 2 }, { year: 2026 }, { level: "B", type: "journal" }, { direction: "llm,agent" }, { year: 2001 }]) {
    const download = vi.fn(async path => ({ data: values.get(path) }));
    const current = createLazyReader({ manifest: data.manifest, catalog: { ...fixture.catalog, reader: descriptor }, download });
    const actual = await current.call("papers", params), expected = full.papers(params);
    expect(actual.total).toBe(expected.total);
    expect(actual.items.map(p => p.id)).toEqual(expected.items.map(p => p.id));
    if (params.venue === "BJ") expect(download).toHaveBeenCalledTimes(2);
    if (params.year === 2001) expect(download).not.toHaveBeenCalled();
    expect(download.mock.calls.every(([path]) => path.startsWith("browse-"))).toBe(true);
  }
});


it("defers the detached descriptor until a paper/search operation and deduplicates concurrent loads", async () => {
  const sha256 = 'a'.repeat(64);
  const path = 'reader-' + sha256 + '.json.gz';
  const download = vi.fn(async name => ({ data: name === path ? data.reader : JSON.parse(gunzipSync(readFileSync(join(directory, name)))) }));
  const detached = { version: 4, paper_count: data.manifest.paper_count, index: { path, sha256, count: data.manifest.paper_count } };
  const current = createLazyReader({ manifest: data.manifest, catalog: { ...fixture.catalog, reader: detached }, download });
  expect(download).not.toHaveBeenCalled();
  const results = await Promise.all([current.call('papers', {}), current.call('search', { q: fixture.papers[0].title, match: 'exact' })]);
  expect(results[0].total).toBe(data.manifest.paper_count);
  expect(results[1].items[0].id).toBe(11);
  expect(download.mock.calls.filter(([name]) => name === path)).toHaveLength(1);
});

it("scoped searches do not download cards outside the candidate metadata ranges", async () => {
  const descriptor = structuredClone(data.reader), values = new Map();
  descriptor.browse = fixture.papers.map(paper => {
    const rows = [descriptor.fields.map(field => paper[field])];
    const sha256 = createHash('sha256').update(JSON.stringify(rows)).digest('hex');
    const path = 'browse-' + sha256 + '.json.gz'; values.set(path, rows);
    return { path, sha256, count: 1, min_id: paper.id, max_id: paper.id };
  });
  const download = vi.fn(async path => ({ data: values.get(path) ?? JSON.parse(gunzipSync(readFileSync(join(directory, path)))) }));
  const current = createLazyReader({ manifest: data.manifest, catalog: { ...fixture.catalog, reader: descriptor }, download });
  const params = { q: 'retrieval', venue: 'BJ' };
  const result = await current.call('search', params);
  expect(result.items.map(p => p.id)).toEqual(createSnapshotEngine(fixture).search(params).items.map(p => p.id));
  for (const [path] of download.mock.calls.filter(([path]) => path.startsWith('browse-'))) {
    expect(values.get(path).every(row => row[2] === 'BJ')).toBe(true);
  }
});


function pagedReader({ mutate = () => {}, intercept = (_args, load) => load() } = {}) {
  const descriptor = structuredClone(data.paged), values = new Map();
  descriptor.browse = fixture.papers.map(paper => {
    const rows = [descriptor.fields.map(field => paper[field])];
    const sha256 = createHash('sha256').update(JSON.stringify(rows)).digest('hex');
    const path = 'browse-' + sha256 + '.json.gz'; values.set(path, rows);
    return { path, sha256, count: 1, min_id: paper.id, max_id: paper.id };
  });
  mutate(descriptor);
  const download = vi.fn(async (...args) => intercept(args, () => ({
    data: values.get(args[0]) ?? JSON.parse(gunzipSync(readFileSync(join(directory, args[0])))),
  })));
  return { download, values, descriptor, reader: createLazyReader({ manifest: data.manifest, catalog: { ...fixture.catalog, reader: descriptor }, download }) };
}

it('ranks all candidates before loading only the requested page, preserving filters and every sort', async () => {
  const full = createSnapshotEngine(fixture);
  for (const method of ['papers', 'search']) for (const sort of ['publication_desc', 'created_desc', 'year_desc', 'citation_desc', ...(method === 'search' ? ['relevance'] : [])]) {
    for (const extra of [{}, {venue:'BJ'}, {direction:'llm,agent'}, {access:'oa'}, {access:'official'}, {year:2025}, {pdf_status:'pending'}, {level:'B',type:'journal'}, {page:2}]) {
      const current = pagedReader(), params = {q:'retrieval', size:1, sort, ...extra};
      const actual = await current.reader.call(method, params), expected = full[method](params);
      expect(actual.total).toBe(expected.total);
      expect(actual.items.map(({id,score})=>({id,score}))).toEqual(expected.items.map(({id,score})=>({id,score})));
      const fetched = current.download.mock.calls.filter(([name])=>name.startsWith('browse-'));
      expect(fetched).toHaveLength(expected.items.length);
      for (const [name] of fetched) expect(expected.items.some(p=>p.id===current.values.get(name)[0][0])).toBe(true);
      expect(current.download.mock.calls.some(([name])=>/^(compressed|papers)-/.test(name))).toBe(false);
    }
  }
});

it('position-aware ranked search preserves exact Unicode, phrase, AND, typo and prefix scores', async () => {
  const full = createSnapshotEngine(fixture), current = pagedReader();
  for (const q of [...fixture.papers.map(p=>p.title), 'spceulative dec', 'speculativ decoding decoding', 'retrieval model', 'onlyabstract', 'absenttermxyz']) {
    for (const match of ['auto','keywords','exact','fuzzy']) {
      const params={q,match,size:100}, actual=await current.reader.call('search',params), expected=full.search(params);
      expect(actual.total, q+' '+match).toBe(expected.total);
      expect(actual.items.map(({id,score})=>({id,score})),q+' '+match).toEqual(expected.items.map(({id,score})=>({id,score})));
      expect(actual.match_mode).toBe(expected.match_mode);
      expect(actual.query_expansions).toEqual(expected.query_expansions);
    }
  }
});

it.each(["spec dec", "SPEC DEC", "  SpEc   DeC  ", "ＳＰＥＣ ＤＥＣ"])("keeps lazy and ranked fragment search consistent: %s", async (q) => {
  const full = createSnapshotEngine(fixture);
  for (const current of [reader(), pagedReader()]) {
    for (const match of ["auto", "fuzzy"]) {
      const params = { q, match, direction: "llm", size: 100 };
      const actual = await current.reader.call("search", params);
      expect(actual.items.some(paper => paper.id === 11)).toBe(true);
      expect(actual.items.map(paper => paper.id)).toEqual(full.search(params).items.map(paper => paper.id));
    }
    expect(current.download.mock.calls.every(([path]) => !/^(compressed|papers)-/.test(path))).toBe(true);
  }
});

it('cancels abandoned card downloads and can immediately retry without poisoned cached promises', async () => {
  const controller = new AbortController();
  let started, blockedSignal, first = true;
  const active = new Promise(resolve => { started = resolve; });
  const download = vi.fn(async (path, digest, cache, maxBytes, signal) => {
    if (path.startsWith('browse-') && first) {
      first = false; blockedSignal = signal; started();
      await new Promise((resolve, reject) => signal?.addEventListener('abort', () => reject(signal.reason), { once: true }));
    }
    return { data: JSON.parse(gunzipSync(readFileSync(join(directory, path)))) };
  });
  const lazy = createLazyReader({ manifest: data.manifest, catalog: { ...fixture.catalog, reader: data.paged }, download });
  const abandoned = lazy.call('papers', {}, { signal: controller.signal });
  const check = expect(abandoned).rejects.toMatchObject({ name: 'AbortError' });
  await active; controller.abort(); await check;
  expect(blockedSignal.aborted).toBe(true);
  const again = await lazy.call('papers');
  expect(again.total).toBe(fixture.papers.length);
});



it('keeps shared ranking metadata hot for immediate sidebar navigation after search', async () => {
  const current = pagedReader(), full = createSnapshotEngine(fixture);
  await current.reader.call('search', { q: 'model' });
  const firstCalls = current.download.mock.calls.length;
  const actual = await current.reader.call('papers', { direction: 'llm' });
  expect(actual.items.map(p => p.id)).toEqual(full.papers({ direction: 'llm' }).items.map(p => p.id));
  expect(current.download.mock.calls.slice(firstCalls).some(([path]) => path.startsWith('ranking-'))).toBe(false);
});

it('does not mutate verified raw ranking arrays while reusing queries and filters', async () => {
  const originals = [];
  const current = pagedReader({ intercept: ([path], load) => {
    const result = load();
    if (path.startsWith('ranking-')) originals.push([result.data, JSON.stringify(result.data)]);
    return result;
  } });
  for (const [method, params] of [['search', { q: 'model' }], ['papers', { direction: 'agent' }],
    ['search', { q: 'retrieval', sort: 'citation_desc' }], ['papers', { venue: 'AC', year: 2025 }]]) {
    await current.reader.call(method, params);
  }
  expect(originals.length).toBeGreaterThan(0);
  for (const [data, before] of originals) expect(JSON.stringify(data)).toBe(before);
});

it('computes each term group IDF once rather than once per candidate', async () => {
  const current = pagedReader();
  const expected = createSnapshotEngine(fixture).search({ q: 'model', match: 'keywords' });
  const log = vi.spyOn(Math, 'log');
  let actual, calls;
  try {
    actual = await current.reader.call('search', { q: 'model', match: 'keywords' });
    calls = log.mock.calls.length;
  } finally { log.mockRestore(); }
  expect(actual.items.map(({ id, score }) => ({ id, score }))).toEqual(expected.items.map(({ id, score }) => ({ id, score })));
  expect(calls).toBe(1);
});

it('still rejects dangling off-page postings before displaying any cards', async () => {
  const current = pagedReader({ intercept: ([path], load) => {
    const value = load();
    return path.startsWith('search-') && value.data.some(row => row[0] === 'model')
      ? { ...value, data: value.data.map(row => row[0] === 'model' && row[1] === 23 ? ['model', 12, 1, 100000, []] : row) } : value;
  } });
  await expect(current.reader.call('search', { q: 'model', size: 1 })).rejects.toMatchObject({ code: 'INVALID_SNAPSHOT' });
  expect(current.download.mock.calls.some(([path]) => path.startsWith('browse-'))).toBe(false);
});

it('starts independent postings while exact-title lookup is still pending', async () => {
  let release;
  const titleGate = new Promise(resolve => { release = resolve; });
  const current = pagedReader({
    intercept: async ([path], load) => { if (path.startsWith('titles-')) await titleGate; return load(); },
  });
  const result = current.reader.call('search', { q: fixture.papers[0].title });
  try {
    await vi.waitFor(() => expect(current.download.mock.calls.some(([path]) => path.startsWith('search-'))).toBe(true), { timeout: 300, interval: 5 });
  } finally { release(); }
  expect((await result).total).toBe(createSnapshotEngine(fixture).search({ q: fixture.papers[0].title }).total);
});

it('cancels both parallel lookups and does not poison a following search', async () => {
  const signals = new Map(), controller = new AbortController();
  let blocked = true;
  const current = pagedReader({
    intercept: async ([path, , , , signal], load) => {
      if (blocked && /^(titles|search)-/.test(path)) {
        signals.set(path.split('-')[0], signal);
        await new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }));
      }
      return load();
    },
  });
  const result = current.reader.call('search', { q: fixture.papers[0].title }, { signal: controller.signal });
  const cancelled = expect(result).rejects.toMatchObject({ name: 'AbortError' });
  try {
    await vi.waitFor(() => expect([...signals.keys()].sort()).toEqual(['search', 'titles']), { timeout: 300, interval: 5 });
  } finally { controller.abort(); await cancelled; blocked = false; }
  expect([...signals.values()].every(signal => signal.aborted)).toBe(true);
  expect((await current.reader.call('search', { q: fixture.papers[0].title })).total).toBe(createSnapshotEngine(fixture).search({ q: fixture.papers[0].title }).total);
});

it('does not fetch word shards for exact-only, invalid, or long-title-only queries', async () => {
  for (const params of [{ q: fixture.papers[3].title }, { q: '中文 model' },
    { q: 'model '.repeat(60) }, { q: fixture.papers[0].title, match: 'exact' }]) {
    const current = pagedReader();
    try { await current.reader.call('search', params); } catch (error) { expect(error.status).toBe(400); }
    expect(current.download.mock.calls.some(([path]) => /^(search|vocabulary)-/.test(path))).toBe(false);
  }
});

it.each([false, true])('validates overlapping ranking ranges without hiding duplicate IDs: duplicate=%s', duplicate => {
  const assets = new Map();
  const current = pagedReader({
    mutate: descriptor => {
      const encoded = JSON.parse(gunzipSync(readFileSync(join(directory, descriptor.ranking.parts[0].path))));
      let id = 0;
      const rows = encoded.map(row => { id += row[0]; return [id, ...row.slice(1)]; });
      descriptor.ranking.parts = (duplicate ? [[0, 1, 2], [2, 4]] : [[0, 2, 4], [1, 3]]).map(indices => {
        let previous = 0;
        const values = indices.map(index => { const row = rows[index], value = [row[0] - previous, ...row.slice(1)]; previous = row[0]; return value; });
        const sha256 = createHash('sha256').update(JSON.stringify(values)).digest('hex');
        const path = `ranking-${sha256}.json.gz`; assets.set(path, values);
        return { path, sha256, count: values.length, min_id: rows[indices[0]][0], max_id: rows[indices.at(-1)][0] };
      });
    },
    intercept: ([path], load) => assets.has(path) ? { data: assets.get(path) } : load(),
  });
  const result = current.reader.call('search', { q: 'model', size: 1 });
  if (duplicate) return expect(result).rejects.toMatchObject({ code: 'INVALID_SNAPSHOT' });
  return result.then(actual => {
    const expected = createSnapshotEngine(fixture).search({ q: 'model', size: 1 });
    expect(actual.total).toBe(expected.total);
    expect(actual.items.map(({ id, score }) => ({ id, score }))).toEqual(expected.items.map(({ id, score }) => ({ id, score })));
  });
});

it('does not revisit raw ranking rows on navigation after the first search', async () => {
  let rawReads = 0;
  const current = pagedReader({ intercept: ([path], load) => {
    const value = load();
    if (!path.startsWith('ranking-')) return value;
    return { ...value, data: value.data.map(row => new Proxy(row, {
      get(target, key, receiver) {
        if (typeof key === 'string' && /^\d+$/.test(key)) rawReads++;
        return Reflect.get(target, key, receiver);
      },
    })) };
  } });
  await current.reader.call('search', { q: 'model' });
  rawReads = 0;
  const result = await current.reader.call('papers', { direction: 'llm' });
  expect(result.items.map(p => p.id)).toEqual(createSnapshotEngine(fixture).papers({ direction: 'llm' }).items.map(p => p.id));
  expect(rawReads).toBe(0);
});
