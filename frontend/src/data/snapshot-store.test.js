import { createHash, webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { snapshotFixture } from "../test/snapshot-fixture.js";

function content(value, prefix) {
  const text = JSON.stringify(value);
  const sha256 = createHash("sha256").update(text).digest("hex");
  return { entry: { path: `${prefix}-${sha256}.json`, sha256 }, text };
}
function bundle(fixture = snapshotFixture()) {
  const catalog = content(fixture.catalog, "catalog"), papers = content(fixture.papers, "papers");
  const manifest = { ...fixture.manifest, catalog: catalog.entry, chunks: [{ ...papers.entry, count: fixture.papers.length }] };
  return { manifest, files: { "manifest.json": JSON.stringify(manifest), [catalog.entry.path]: catalog.text, [papers.entry.path]: papers.text } };
}
const response = (text, status = 200) => ({ ok: status === 200, status, text: async () => text });

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => vi.unstubAllGlobals());

describe("atomic static snapshot loading", () => {
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
