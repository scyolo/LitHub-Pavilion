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


function pagedReader() {
  const descriptor = structuredClone(data.paged), values = new Map();
  descriptor.browse = fixture.papers.map(paper => {
    const rows = [descriptor.fields.map(field => paper[field])];
    const sha256 = createHash('sha256').update(JSON.stringify(rows)).digest('hex');
    const path = 'browse-' + sha256 + '.json.gz'; values.set(path, rows);
    return { path, sha256, count: 1, min_id: paper.id, max_id: paper.id };
  });
  const download = vi.fn(async path => ({ data: values.get(path) ?? JSON.parse(gunzipSync(readFileSync(join(directory, path)))) }));
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
