import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import { createSnapshotStore } from "../src/data/snapshot-store.js";

const directory = new URL("../static/snapshot/", import.meta.url);
const manifest = JSON.parse(await readFile(new URL("manifest.json", directory), "utf8"));
const requests = [];
let bytes = 0;
const store = createSnapshotStore({
  baseUrl: "https://reader.example/snapshot/",
  fetcher: async (url, options) => {
    const parsed = new URL(url);
    assert.equal(parsed.origin, "https://reader.example");
    assert.ok(parsed.pathname.startsWith("/snapshot/"));
    const name = parsed.pathname.slice("/snapshot/".length);
    assert.ok(name === "manifest.json" || /^catalog-[0-9a-f]{64}\.json$/.test(name),
      `Homepage must not request full paper data: ${name}`);
    assert.equal(options.credentials, "omit");
    const content = await readFile(new URL(name, directory));
    requests.push(name);
    bytes += content.byteLength;
    return new Response(content, { headers: { "content-type": "application/json" } });
  },
});
const started = performance.now();
const [dashboard, directions, latest, status] = await Promise.all([
  store.call("dashboard", {}), store.call("directions"), store.call("latest", {}), store.call("crawlStatus"),
]);
assert.equal(dashboard.total, manifest.paper_count);
assert.equal(latest.total, manifest.paper_count);
assert.equal(status.revision, manifest.revision);
assert.equal(status.generated_at, manifest.generated_at);
assert.ok(directions.items.length > 0);
for (const level of [null, "A", "B"]) for (const type of [null, "conf", "journal"]) {
  const scoped = await store.call("dashboard", { level, type });
  const recent = await store.call("latest", { level, type });
  assert.equal(scoped.total, recent.total);
  assert.equal(scoped.generated_at, manifest.generated_at);
}
assert.equal(requests.length, 2);
assert.ok(bytes <= 512 * 1024, `Homepage metadata exceeds 512 KiB: ${bytes}`);
assert.equal(store.getState().verification, "catalog");
console.log(JSON.stringify({
  homepage_files: requests.length, paper_chunks_requested: 0, metadata_bytes: bytes,
  paper_count: dashboard.total, revision: manifest.revision,
  processing_ms: Math.round(performance.now() - started),
}));
