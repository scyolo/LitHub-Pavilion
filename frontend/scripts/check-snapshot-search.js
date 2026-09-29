/** Real-data smoke test through the same integrity-checking reader used by the site.
 * Run after exporting: node scripts/check-snapshot-search.js [report.json]
 * This is Node acceptance evidence, not a browser/mobile performance benchmark.
 */
import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import { createSnapshotStore } from "../src/data/snapshot-store.js";

const directory = new URL("../static/snapshot/", import.meta.url);
const manifest = JSON.parse(await readFile(new URL("manifest.json", directory), "utf8"));
const allowed = new Set(["manifest.json", manifest.catalog.path, ...manifest.chunks.map((entry) => entry.path)]);
const normalize = (text) => text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const supported = (paper) => paper.title.length <= 2000 && normalize(paper.title).length > 0;
const samples = new Map(), unicode = [], arxiv = [];
const requests = [];
let bytes = 0, maxChunkBytes = 0, unsupportedTitles = 0;
const store = createSnapshotStore({
  baseUrl: "https://reader.example/snapshot/",
  fetcher: async (url, options) => {
    const parsed = new URL(url);
    assert.equal(parsed.origin, "https://reader.example");
    assert.ok(parsed.pathname.startsWith("/snapshot/"));
    const name = parsed.pathname.slice("/snapshot/".length);
    assert.ok(allowed.has(name), `Unexpected asset: ${name}`);
    assert.equal(options.credentials, "omit");
    const content = await readFile(new URL(name, directory));
    requests.push(name);
    bytes += content.byteLength;
    if (name.startsWith("papers-")) {
      maxChunkBytes = Math.max(maxChunkBytes, content.byteLength);
      for (const paper of JSON.parse(content)) {
        if (!supported(paper)) { unsupportedTitles++; continue; }
        const key = `${paper.venue}:${paper.year}`;
        if (!samples.has(key)) samples.set(key, paper);
        if (unicode.length < 12 && /[^\x20-\x7e]/u.test(paper.title)) unicode.push(paper);
        if (arxiv.length < 12 && (paper.arxiv_id || /arxiv\.org\//.test(paper.oa_url || ""))
            && paper.venue_confirmed && paper.official_url && !/arxiv\.org\//.test(paper.official_url)) arxiv.push(paper);
      }
    }
    return new Response(content, { headers: { "content-type": "application/json" } });
  },
});
const started = performance.now();
const listing = await store.call("papers", { page: 1, size: 100 });
const loadedAt = performance.now();
assert.equal(listing.total, manifest.paper_count);
assert.equal(store.getState().verification, "full");
const coverage = await store.call('verifyTitleCoverage');
assert.equal(coverage.checked, manifest.paper_count, JSON.stringify(coverage.failures));
assert.deepEqual(coverage.failures, []);
assert.equal(unsupportedTitles, 0, 'Every indexed title must be queryable');
assert.equal(new Set(requests).size, manifest.chunks.length + 2);
assert.equal(requests.length, manifest.chunks.length + 2);
const last = await store.call("papers", { page: Math.max(1, Math.ceil(manifest.paper_count / 100)), size: 100 });
assert.equal(last.items.length, manifest.paper_count ? ((manifest.paper_count - 1) % 100) + 1 : 0);
let exactChecks = 0, andChecks = 0;
const results = [];
const checks = [...new Map([...samples.values(), ...unicode, ...arxiv].map((p) => [p.id, p])).values()];
for (const paper of checks) {
  const result = await store.call("search", { q: paper.title, size: 100 });
  assert.ok(result.total > 0, `Full title not found: ${paper.id} ${paper.title}`);
  assert.equal(normalize(result.items[0].title), normalize(paper.title), `Exact title not first: ${paper.title}`);
  assert.ok(result.items.some((p) => p.id === paper.id), `Expected identity missing: ${paper.id}`);
  exactChecks++;
  results.push({ id: paper.id, venue: paper.venue, year: paper.year, title: paper.title, matches: result.total });
  const tokens = normalize(paper.title).split(" ");
  if (andChecks < 16 && tokens.length >= 6 && !/[^\x20-\x7e]/u.test(paper.title)) {
    const q = [tokens[0], tokens[Math.floor(tokens.length / 2)], tokens.at(-1)].join(" ");
    const scattered = await store.call("search", { q, venue: paper.venue, year: paper.year, size: 100 });
    assert.ok(scattered.items.some((p) => p.id === paper.id), `Non-adjacent AND recall failed: ${paper.id}, ${q}`);
    andChecks++;
  }
}
for (const sample of arxiv) {
  const detail = await store.call("paper", sample.id);
  assert.ok(detail.arxiv_id || /arxiv\.org\//.test(detail.oa_url || ""));
  assert.equal(detail.year, sample.year);
  assert.equal(detail.venue.abbr, sample.venue);
}
assert.ok(exactChecks > 0 && andChecks > 0 && arxiv.length > 0 && unicode.length > 0);
const report = {
  generated_at: new Date().toISOString(), revision: manifest.revision, paper_count: manifest.paper_count,
  integrity: store.getState().verification, chunks: manifest.chunks.length, requested_files: requests.length,
  downloaded_bytes: bytes, largest_chunk_bytes: maxChunkBytes, load_ms: Math.round(loadedAt - started),
  total_ms: Math.round(performance.now() - started), heap_used_bytes: process.memoryUsage().heapUsed,
  exact_title_checks: exactChecks, all_title_identity_checks: coverage.checked, unique_title_keys: coverage.unique_titles,
  all_titles_queryable: coverage.checked === manifest.paper_count && !coverage.failures.length,
  venue_year_samples: samples.size, non_adjacent_and_checks: andChecks,
  unicode_title_checks: unicode.length, arxiv_detail_checks: arxiv.length,
  titles_outside_existing_query_contract: unsupportedTitles,
  browser_mobile_performance_verified: false, samples: results,
};
if (process.argv[2]) await writeFile(process.argv[2], JSON.stringify(report, null, 2), "utf8");
const { samples: checkedSamples, ...summary } = report;
console.log(JSON.stringify(summary));
