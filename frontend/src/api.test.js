import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./data/snapshot-client.js", () => ({
  snapshotCall: vi.fn(async (method, params) => ({ method, params, source: "snapshot" })),
  getSnapshotState: vi.fn(),
  subscribeSnapshot: vi.fn(),
}));

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(body) };
}

async function setup(mode) {
  vi.resetModules();
  vi.stubEnv("VITE_DATA_MODE", mode);
  const { api } = await import("./api.js");
  const { snapshotCall } = await import("./data/snapshot-client.js");
  return { api, snapshotCall };
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.useRealTimers(); });

describe("data source selection", () => {
  it("never requests an API or health endpoint in the published snapshot reader", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const { api, snapshotCall } = await setup("snapshot");
    await api.papers({ year: 2025 });
    await api.paper(11);
    await api.checkConnection();
    await expect(api.trigger({ scope: "weekly" })).rejects.toMatchObject({ code: "READ_ONLY" });
    expect(api.useHashRouting).toBe(true);
    expect(snapshotCall).toHaveBeenCalledWith("paper", 11, undefined);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("falls back on connection loss, keeps interactions local and recovers when the backend starts", async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetcher);
    const { api, snapshotCall } = await setup("auto");
    const changed = vi.fn();
    const unsubscribe = api.subscribeData(changed);
    expect(api.useHashRouting).toBe(false);
    expect(await api.papers({ year: 2025 })).toMatchObject({ source: "snapshot" });
    expect(api.isSnapshot).toBe(true);
    expect(changed).toHaveBeenCalledTimes(1);
    await api.search({ q: "decoding" });
    expect(snapshotCall).toHaveBeenCalledWith("search", { q: "decoding" }, undefined);
    expect(fetcher).toHaveBeenCalledTimes(1);
    fetcher.mockResolvedValue(response({ status: "ok", db: "ok" }));
    expect(await api.checkConnection()).toBe(true);
    expect(api.isSnapshot).toBe(false);
    expect(changed).toHaveBeenCalledTimes(2);
    fetcher.mockResolvedValue(response({ id: 11, title: "Live record" }));
    expect(await api.paper(11)).toMatchObject({ title: "Live record" });
    unsubscribe();
  });
  it.each([400, 403, 404, 409, 429])("does not replace a real API error %s with an old snapshot", async (status) => {
    vi.stubGlobal("fetch", vi.fn(async () => response({ error: { message: "API validation" } }, status)));
    const { api, snapshotCall } = await setup("auto");
    await expect(api.paper(999)).rejects.toMatchObject({ status });
    expect(api.isSnapshot).toBe(false);
    expect(snapshotCall).not.toHaveBeenCalled();
  });
  it("falls back when a static server returns HTML for an unavailable API", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, text: async () => "<!doctype html>" })));
    const { api } = await setup("auto");
    expect(await api.dashboard()).toMatchObject({ source: "snapshot" });
    expect(api.isSnapshot).toBe(true);
  });
  it("does not recover to a backend whose database is not ready", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({ status: "degraded", db: "error" }, 503)));
    const { api } = await setup("auto");
    expect(await api.checkConnection()).toBe(false);
    expect(api.isSnapshot).toBe(true);
  });
  it("shares concurrent connection checks", async () => {
    const fetcher = vi.fn(async () => response({ status: "ok", db: "ok" }));
    vi.stubGlobal("fetch", fetcher);
    const { api } = await setup("auto");
    await Promise.all([api.checkConnection(), api.checkConnection()]);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("does not switch source when a route change cancels a request", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const { api } = await setup("auto");
    const controller = new AbortController();
    controller.abort();
    await expect(api.papers({}, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(api.isSnapshot).toBe(false);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("times out an unresponsive backend instead of leaving the reader loading forever", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new DOMException("Timeout", "AbortError")));
    })));
    const { api } = await setup("auto");
    const pending = api.papers({});
    await vi.advanceTimersByTimeAsync(8000);
    expect(await pending).toMatchObject({ source: "snapshot" });
  });
  it("does not retry mutation requests against either the snapshot or the live API", async () => {
    const fetcher = vi.fn(async () => response({ error: { message: "unavailable" } }, 503));
    vi.stubGlobal("fetch", fetcher);
    const { api, snapshotCall } = await setup("auto");
    await expect(api.trigger({ scope: "weekly" })).rejects.toMatchObject({ status: 503 });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(snapshotCall).not.toHaveBeenCalled();
  });
  it("keeps explicit API-only mode strict", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const { api, snapshotCall } = await setup("api");
    await expect(api.papers({})).rejects.toThrow("Failed to fetch");
    expect(api.isSnapshot).toBe(false);
    expect(snapshotCall).not.toHaveBeenCalled();
  });
});
