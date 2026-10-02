import { createHash, webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { withOverview } from "../test/snapshot-fixture.js";
import { createSnapshotStore } from "./snapshot-store.js";
const canonical = v => v && typeof v === "object" ? Array.isArray(v) ? v.map(canonical) : Object.fromEntries(Object.keys(v).sort().map(k => [k, canonical(v[k])])) : v;
const text = v => JSON.stringify(canonical(v));
const hash = v => createHash("sha256").update(v).digest("hex");
function saved(pretty = false) {
  const f = withOverview();
  const catalogText = pretty ? JSON.stringify(f.catalog, null, 2) : text(f.catalog);
  const ch = hash(catalogText), ph = hash(text(f.papers));
  const manifest = { ...f.manifest, catalog: { path: `catalog-${ch}.json`, sha256: ch }, chunks: [{ path: `papers-${ph}.json`, sha256: ph, count: f.papers.length }] };
  manifest.revision = hash(text({ schema_version: 1, paper_count: manifest.paper_count, catalog: manifest.catalog, chunks: manifest.chunks }));
  return { manifest, catalog_text: catalogText };
}
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => vi.unstubAllGlobals());
describe("verified overview warm start", () => {
  it("verifies original catalogue bytes rather than reserialized JavaScript objects", async () => {
    const data = saved(true);
    const fetcher = vi.fn(async () => new Response(text(data.manifest)));
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher, overviewCache: { read: async () => data } });
    expect((await store.call("dashboard", {})).total).toBe(data.manifest.paper_count);
    await store.refresh();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("renders a verified cached overview before a slow network", async () => {
    const data = saved();
    let resolve;
    const fetcher = vi.fn(() => new Promise(done => { resolve = done; }));
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher, overviewCache: { read: async () => data } });
    expect((await store.call("dashboard", {})).total).toBe(data.manifest.paper_count);
    expect(store.getState().from_cache).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(1);
    resolve(new Response(JSON.stringify(data.manifest)));
    await store.refresh();
    expect(store.getState().from_cache).toBe(false);
  });
  it("rejects modified cached metadata and downloads a verified copy", async () => {
    const data = saved(), tampered = structuredClone(data);
    const parsed = JSON.parse(tampered.catalog_text);
    parsed.venues[0].name = "tampered";
    tampered.catalog_text = text(parsed);
    const overviewCache = { read: async () => tampered, clear: vi.fn(async () => {}), write: vi.fn(async () => {}) };
    const fetcher = vi.fn(async url => new Response(url.endsWith("manifest.json") ? text(data.manifest) : data.catalog_text));
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher, overviewCache });
    expect((await store.call("dashboard", {})).total).toBe(data.manifest.paper_count);
    expect(overviewCache.clear).toHaveBeenCalled();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("retains the dated overview if background revalidation is offline", async () => {
    const data = saved();
    const fetcher = vi.fn(async () => { throw new TypeError("offline"); });
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher, overviewCache: { read: async () => data } });
    expect((await store.call("dashboard", {})).total).toBe(data.manifest.paper_count);
    await store.refresh().catch(() => {});
    expect((await store.call("dashboard", {})).generated_at).toBe(data.manifest.generated_at);
    expect(store.getState().error).toBeTruthy();
  });
});
