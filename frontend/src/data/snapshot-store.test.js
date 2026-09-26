import { createHash, webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { snapshotFixture, withOverview } from "../test/snapshot-fixture.js";

function content(value, prefix) {
  const text = JSON.stringify(value);
  const sha256 = createHash("sha256").update(text).digest("hex");
  return { entry: { path: `${prefix}-${sha256}.json`, sha256 }, text };
}
function bundle(fixture = snapshotFixture()) {
  const catalog = content(fixture.catalog, "catalog"), papers = content(fixture.papers, "papers");
  const manifest = { ...fixture.manifest, catalog: catalog.entry, chunks: [{ ...papers.entry, count: fixture.papers.length }] };
  const canonical = (value) => value && typeof value === "object" ? Array.isArray(value) ? value.map(canonical) : Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])])) : value;
  manifest.revision = createHash("sha256").update(JSON.stringify(canonical({ schema_version: 1, paper_count: manifest.paper_count, catalog: manifest.catalog, chunks: manifest.chunks }))).digest("hex");
  return { manifest, files: { "manifest.json": JSON.stringify(manifest), [catalog.entry.path]: catalog.text, [papers.entry.path]: papers.text } };
}
const response = (text, status = 200) => ({ ok: status === 200, status, text: async () => text });

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => vi.unstubAllGlobals());

describe("atomic static snapshot loading", () => {
  it("renders all home queries from two verified files without downloading papers", async () => {
    const { createSnapshotStore } = await import("./snapshot-store.js");
    const data = bundle(withOverview());
    const fetcher = vi.fn(async (url) => response(data.files[String(url).split("/").pop()]));
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher });
    const [dashboard, directions, status, latest] = await Promise.all([store.call("dashboard", {}), store.call("directions"), store.call("crawlStatus"), store.call("latest", {})]);
    expect(dashboard.total).toBe(3);
    expect(directions.items).toHaveLength(3);
    expect(status.read_only).toBe(true);
    expect(latest.items.map((p) => p.id)).toEqual([35, 11, 23]);
    expect(latest.items[0]).not.toHaveProperty("abstract");
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(store.getState()).toMatchObject({ status: "ready", verification: "catalog", revision: data.manifest.revision });
    for (const level of [null, "A", "B"]) for (const type of [null, "conf", "journal"]) await store.call("dashboard", { level, type });
    expect(fetcher).toHaveBeenCalledTimes(2);
    await store.call("paper", 11);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(store.getState()).toMatchObject({ verification: "full", revision: data.manifest.revision });
  });
  it("keeps verified overview usable if full data fails and retries only on demand", async () => {
    const { createSnapshotStore } = await import("./snapshot-store.js");
    const data = bundle(withOverview());
    let fail = true;
    const fetcher = vi.fn(async (url) => {
      const name = String(url).split("/").pop();
      return name.startsWith("papers-") && fail ? response("missing", 404) : response(data.files[name]);
    });
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher });
    await store.call("dashboard", {});
    await expect(store.call("papers", {})).rejects.toThrow();
    expect((await store.call("dashboard", {})).total).toBe(3);
    expect(store.getState()).toMatchObject({ status: "ready", verification: "catalog" });
    fail = false;
    expect((await store.call("papers", {})).total).toBe(3);
    expect(store.getState().verification).toBe("full");
  });
  it("does not downgrade a complete active version when refreshed overview precedes broken chunks", async () => {
    const { createSnapshotStore } = await import("./snapshot-store.js");
    const first = bundle(withOverview());
    const fixture = snapshotFixture(); fixture.papers[0].title = "New title";
    const next = bundle(withOverview(fixture));
    let active = first;
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher: async (url) => {
      const name = String(url).split("/").pop();
      return active === next && name.startsWith("papers-") ? response("missing", 404) : response(active.files[name]);
    } });
    await store.load(); active = next;
    await expect(store.refresh()).rejects.toThrow();
    expect((await store.call("paper", 11)).title).toBe("Speculative decoding for models");
    expect(store.getState()).toMatchObject({ verification: "full", revision: first.manifest.revision });
  });
  it.each(["count", "scope", "url", "private"])("rejects a signed but invalid overview: %s", async (mutation) => {
    const { createSnapshotStore } = await import("./snapshot-store.js");
    const fixture = withOverview();
    const overview = fixture.catalog.overview;
    if (mutation === "count") overview.scopes[0].dashboard.total++;
    if (mutation === "scope") overview.scopes.pop();
    if (mutation === "url") overview.scopes[0].latest[0].official_url = "javascript:alert(1)";
    if (mutation === "private") overview.scopes[0].latest[0].note = "private";
    const data = bundle(fixture);
    const fetcher = vi.fn(async (url) => response(data.files[String(url).split("/").pop()]));
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher });
    await expect(store.call("dashboard", {})).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("validates the manifest content revision before trusting its catalog", async () => {
    const { createSnapshotStore } = await import("./snapshot-store.js");
    const data = bundle(withOverview());
    data.manifest.revision = "f".repeat(64);
    data.files["manifest.json"] = JSON.stringify(data.manifest);
    const fetcher = vi.fn(async (url) => response(data.files[String(url).split("/").pop()]));
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher });
    await expect(store.call("dashboard", {})).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("upgrades an in-flight catalog refresh when full data is requested", async () => {
    const { createSnapshotStore } = await import("./snapshot-store.js");
    const first = bundle(withOverview());
    const fixture = snapshotFixture(); fixture.papers[0].title = "Next snapshot title";
    const next = bundle(withOverview(fixture));
    let active = first, release;
    const gate = new Promise((resolve) => { release = resolve; });
    let blockCatalog = false;
    const fetcher = vi.fn(async (url) => {
      const name = String(url).split("/").pop();
      if (blockCatalog && name === next.manifest.catalog.path) await gate;
      return response(active.files[name]);
    });
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher });
    await store.call("dashboard", {});
    active = next; blockCatalog = true;
    const refresh = store.refresh();
    const paper = store.call("paper", 11);
    release();
    await refresh;
    expect((await paper).title).toBe("Next snapshot title");
    expect(store.getState()).toMatchObject({ verification: "full", generation: 1, revision: next.manifest.revision });
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("papers-")).length).toBe(1);
  });
  it("loads full data for filters not represented by the home overview", async () => {
    const { createSnapshotStore } = await import("./snapshot-store.js");
    const data = bundle(withOverview());
    const fetcher = vi.fn(async (url) => response(data.files[String(url).split("/").pop()]));
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher });
    expect((await store.call("dashboard", { direction: "agent", year: "2024" })).total).toBe(1);
    expect(fetcher).toHaveBeenCalledTimes(3);
    await expect(store.call("dashboard", { level: "C" })).rejects.toMatchObject({ status: 400 });
  });
  it("cross-checks a well-formed but altered preview before completing the full version", async () => {
    const { createSnapshotStore } = await import("./snapshot-store.js");
    const fixture = withOverview();
    fixture.catalog.overview.scopes[0].latest[0].title = "Wrong but plausible title";
    const data = bundle(fixture);
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher: async (url) => response(data.files[String(url).split("/").pop()]) });
    await expect(store.load()).rejects.toMatchObject({ code: "INVALID_SNAPSHOT" });
    expect(store.getState()).toMatchObject({ status: "error", revision: null });
  });
  it("loads only same-site files below the Pages repository base", async () => {
    const { createSnapshotStore } = await import("./snapshot-store.js");
    const data = bundle();
    const fetcher = vi.fn(async (url) => response(data.files[String(url).split("/").pop()]));
    const store = createSnapshotStore({ baseUrl: "https://reader.example/LitHub-Pavilion/snapshot/", fetcher });
    expect((await store.call("papers", {})).total).toBe(3);
    expect(fetcher.mock.calls.every(([url]) => String(url).startsWith("https://reader.example/LitHub-Pavilion/snapshot/"))).toBe(true);
    await store.call("paper", 11);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(store.getState()).toMatchObject({ status: "ready", revision: data.manifest.revision });
  });
  it("keeps all old queries usable when a new chunk fails, then atomically switches", async () => {
    const { createSnapshotStore } = await import("./snapshot-store.js");
    const first = bundle();
    const nextFixture = snapshotFixture();
    nextFixture.papers[0].title = "New revision title";
    nextFixture.manifest.revision = "b".repeat(64);
    const next = bundle(nextFixture);
    let active = first, fail = false;
    const fetcher = vi.fn(async (url) => {
      const filename = String(url).split("/").pop();
      return fail && filename.startsWith("papers-") ? response("missing", 404) : response(active.files[filename]);
    });
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher });
    await store.load();
    active = next; fail = true;
    await expect(store.refresh()).rejects.toThrow();
    expect((await store.call("paper", 11)).title).toBe("Speculative decoding for models");
    expect(store.getState()).toMatchObject({ status: "ready", revision: first.manifest.revision });
    expect(store.getState().error).toBeTruthy();
    fail = false;
    expect(await store.refresh()).toBe(true);
    expect((await store.call("paper", 11)).title).toBe("New revision title");
    expect(store.getState().error).toBeNull();
  });
  it.each(["https://attacker.example/file.json", "../private.json", "/api/papers", "papers-invalid.json"])("refuses unsafe manifest path %s before fetching it", async (path) => {
    const { createSnapshotStore } = await import("./snapshot-store.js");
    const data = bundle();
    data.manifest.catalog.path = path;
    const fetcher = vi.fn(async () => response(JSON.stringify(data.manifest)));
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher });
    await expect(store.load()).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("fetches snapshots without credentials or cross-origin redirects", async () => {
    const { createSnapshotStore } = await import("./snapshot-store.js");
    const data = bundle(withOverview());
    const fetcher = vi.fn(async (url) => response(data.files[String(url).split("/").pop()]));
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher });
    await store.call("dashboard", {});
    for (const [, options] of fetcher.mock.calls) expect(options).toMatchObject({ credentials: "omit", redirect: "error", mode: "same-origin" });
  });
  it("rejects corrupted content rather than replacing it with an empty library", async () => {
    const { createSnapshotStore } = await import("./snapshot-store.js");
    const data = bundle();
    data.files[data.manifest.chunks[0].path] = "[]";
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher: async (url) => response(data.files[String(url).split("/").pop()]) });
    await expect(store.load()).rejects.toThrow();
    expect(store.getState().status).toBe("error");
  });
  it("cancels one reader without poisoning the shared initial load", async () => {
    const { createSnapshotStore } = await import("./snapshot-store.js");
    const data = bundle();
    let release;
    const waiting = new Promise((resolve) => { release = resolve; });
    const store = createSnapshotStore({ baseUrl: "https://reader.example/snapshot/", fetcher: async (url) => { await waiting; return response(data.files[String(url).split("/").pop()]); } });
    const controller = new AbortController();
    const abandoned = store.call("papers", {}, controller.signal);
    controller.abort(); release();
    await expect(abandoned).rejects.toMatchObject({ name: "AbortError" });
    expect((await store.call("papers", {})).total).toBe(3);
  });
});
