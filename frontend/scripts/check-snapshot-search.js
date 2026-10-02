import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash, webcrypto } from "node:crypto";
import { gunzipSync } from "node:zlib";
import { pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";
import { createSnapshotStore } from "../src/data/snapshot-store.js";
import { normalizedTitle } from "../src/data/snapshot-engine.js";

if (!globalThis.crypto?.subtle) globalThis.crypto = webcrypto;
const directory = process.env.SNAPSHOT_DIR ? pathToFileURL(resolve(process.env.SNAPSHOT_DIR) + "/") : new URL("../static/snapshot/", import.meta.url);
const manifest = JSON.parse(await readFile(new URL("manifest.json", directory)));
const catalog = JSON.parse(await readFile(new URL(manifest.catalog.path, directory)));
assert.ok(catalog.reader?.version >= 2, "Regenerate the snapshot to enable indexed search");
let descriptor = catalog.reader;
if ([4, 6].includes(descriptor.version)) {
  const raw = gunzipSync(await readFile(new URL(descriptor.index.path, directory)));
  assert.equal(createHash("sha256").update(raw).digest("hex"), descriptor.index.sha256);
  descriptor = JSON.parse(raw);
}
const assets = [...([4, 6].includes(catalog.reader.version) ? [catalog.reader.index] : []), manifest.catalog, ...manifest.chunks, ...descriptor.browse, ...descriptor.details, ...Object.values(descriptor.search.terms).flat(), ...Object.values(descriptor.search.titles).flat(), ...(descriptor.search.vocabulary || []), ...(descriptor.ranking?.parts || [])];
const allowed = new Set(["manifest.json", ...assets.map((entry) => entry.path)]);
const identities = new Map(), samples = new Map();
let unicodeSample;
for (const entry of manifest.chunks) {
  for (const paper of JSON.parse(await readFile(new URL(entry.path, directory)))) {
    identities.set(paper.id, normalizedTitle(paper.title));
    const key = `${paper.venue}:${paper.year}`;
    if (!samples.has(key)) samples.set(key, paper);
    if (!unicodeSample && /[^ -~]/u.test(paper.title)) unicodeSample = paper;
  }
}
const indexed = new Set();
for (const entry of Object.values(descriptor.search.titles).flat()) {
  const raw = gunzipSync(await readFile(new URL(entry.path, directory)));
  assert.equal(createHash("sha256").update(raw).digest("hex"), entry.sha256);
  for (const [title, id] of JSON.parse(raw)) { assert.equal(title, identities.get(id)); assert.ok(!indexed.has(id)); indexed.add(id); }
}
assert.equal(indexed.size, manifest.paper_count);
const requests = [];
let bytes = 0;
const store = createSnapshotStore({
  baseUrl: "https://reader.example/snapshot/",
  fetcher: async (url, options) => {
    const parsed = new URL(url);
    assert.equal(parsed.origin, "https://reader.example");
    const name = parsed.pathname.slice("/snapshot/".length);
    assert.ok(allowed.has(name), `Unexpected asset: ${name}`);
    assert.equal(options.credentials, "omit");
    const content = await readFile(new URL(name, directory));
    requests.push(name); bytes += content.byteLength;
    return new Response(content);
  },
});
const checks = [...new Map([...samples.values(), ...(unicodeSample ? [unicodeSample] : [])].map((paper) => [paper.id, paper])).values()];
const limit = Number(process.env.SEARCH_SAMPLE_LIMIT || 32);
assert.ok(Number.isSafeInteger(limit) && limit > 0, "SEARCH_SAMPLE_LIMIT must be a positive integer");
const selected = checks.filter((_, index) => index % Math.max(1, Math.ceil(checks.length / limit)) === 0);
if (unicodeSample && !selected.includes(unicodeSample)) selected.push(unicodeSample);
const started = performance.now();
let coldSearch, andChecks = 0, directionChecks = 0, autoChecks = 0;
for (const paper of selected) {
  const result = await store.call("search", { q: paper.title, match: "exact", size: 100 });
  assert.ok(result.items.some((row) => row.id === paper.id), `Missing title identity: ${paper.id}`);
  assert.equal(normalizedTitle(result.items[0].title), normalizedTitle(paper.title));
  if (!coldSearch) coldSearch = { ms: Math.round(performance.now() - started), bytes, requests: requests.length };
  for (const direction of paper.directions) {
    const scoped = await store.call("search", { q: paper.title, match: "exact", direction, size: 100 });
    assert.ok(scoped.items.some(row => row.id === paper.id), `Missing direction ${direction} for ${paper.id}`);
    directionChecks++;
  }
  if (autoChecks < 8) {
    const automatic = await store.call("search", { q: paper.title, size: 100 });
    assert.ok(automatic.items.some(row => row.id === paper.id));
    autoChecks++;
  }
  const tokens = normalizedTitle(paper.title).split(" ");
  if (tokens.length >= 6 && andChecks < 8) {
    const result = await store.call("search", { q: [tokens[0], tokens[Math.floor(tokens.length / 2)], tokens.at(-1)].join(" "), venue: paper.venue, year: paper.year, size: 100 });
    assert.ok(result.items.some((row) => row.id === paper.id));
    andChecks++;
  }
}
assert.ok(requests.every((name) => !/^(papers|compressed)-/.test(name)), "Search must never fetch full paper chunks");
const listing = await store.call("papers", { page: 1, size: 100 });
assert.equal(listing.total, manifest.paper_count);
const last = await store.call("papers", { page: Math.ceil(manifest.paper_count / 100), size: 100 });
assert.equal(last.items.length, (manifest.paper_count - 1) % 100 + 1);
const beforeDetail = requests.length;
const detail = await store.call("paper", selected[0].id);
assert.equal(detail.title, selected[0].title);
assert.ok(requests.slice(beforeDetail).every((name) => name.startsWith("compressed-")));
const report = { revision: manifest.revision, paper_count: manifest.paper_count, cold_search: coldSearch, exact_query_checks: selected.length, auto_query_checks: autoChecks, cross_direction_checks: directionChecks, non_adjacent_and_checks: andChecks, offline_title_identity_checks: indexed.size, transferred_bytes: bytes, requested_files: requests.length, detail_requests: requests.length - beforeDetail, total_ms: Math.round(performance.now() - started), browser_mobile_performance_verified: false,
  samples: selected.map(({ id, title, venue, year }) => ({ id, title, venue, year })) };
if (process.argv[2]) {
  await mkdir(dirname(resolve(process.argv[2])), { recursive: true });
  await writeFile(process.argv[2], JSON.stringify(report, null, 2));
}
console.log(JSON.stringify({ ...report, samples: undefined }, null, 2));
