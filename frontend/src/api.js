import { getSnapshotState, snapshotCall, subscribeSnapshot } from "./data/snapshot-client.js";

const mode = import.meta.env.VITE_DATA_MODE || (import.meta.env.PROD ? "snapshot" : "auto");
let dataState = { source: mode === "snapshot" ? "snapshot" : "api", generation: 0 };
const listeners = new Set();
let checking;

function useSource(source) {
  if (source === dataState.source) return;
  dataState = { source, generation: dataState.generation + 1 };
  for (const listener of listeners) listener();
}

async function request(path, { params, signal, timeout = 8000, ...options } = {}) {
  if (signal?.aborted) throw new DOMException("Request aborted", "AbortError");
  const url = new URL(path, window.location.origin);
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) url.searchParams.set(key, String(value));
  });
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, timeout);
  try {
    const response = await fetch(url, { signal: controller.signal, ...options });
    const text = await response.text();
    let body;
    try { body = text ? JSON.parse(text) : null; } catch {
      throw Object.assign(new Error("服务返回了非 JSON 内容，请检查本地 API 代理。"), { status: 503, code: "API_UNAVAILABLE" });
    }
    if (!response.ok) {
      throw Object.assign(new Error(body?.error?.message || `请求失败（${response.status}）`), { code: body?.error?.code, status: response.status });
    }
    return body;
  } catch (error) {
    if (signal?.aborted) throw new DOMException("Request aborted", "AbortError");
    if (controller.signal.aborted) throw Object.assign(new Error("本地后端暂未响应。"), { status: 503, code: "API_UNAVAILABLE" });
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

const liveApi = {
  papers: (params, signal) => request("/api/papers", { params, signal }),
  paper: (id, signal) => request("/api/papers/" + encodeURIComponent(id), { signal }),
  search: (params, signal) => request("/api/search", { params, signal }),
  dashboard: (params, signal) => request("/api/stats/dashboard", { params, signal }),
  directions: (signal) => request("/api/directions", { signal }),
  venues: (params, signal) => request("/api/venues", { params, signal }),
  stats: (signal) => request("/api/stats/overview", { signal }),
  crawlLogs: (page = 1, signal) => request("/api/crawl/logs", { params: { page, size: 10 }, signal }),
  crawlStatus: (signal) => request("/api/crawl/status", { signal }),
};

const staticApi = {
  ...Object.fromEntries(["papers", "paper", "search", "dashboard", "venues", "crawlLogs"].map((method) => [method, (params, signal) => snapshotCall(method, params, signal)])),
  ...Object.fromEntries(["directions", "stats", "crawlStatus"].map((method) => [method, (signal) => snapshotCall(method, undefined, signal)])),
};

async function read(method, args) {
  if (dataState.source === "snapshot") return staticApi[method](...args);
  try {
    return await liveApi[method](...args);
  } catch (error) {
    if (mode !== "auto" || error.name === "AbortError" || (error.status && error.status < 500)) throw error;
    useSource("snapshot");
    return staticApi[method](...args);
  }
}

export const api = {
  ...Object.fromEntries(Object.keys(liveApi).map((method) => [method, (...args) => read(method, args)])),
  get isSnapshot() { return dataState.source === "snapshot"; },
  isAuto: mode === "auto",
  useHashRouting: mode === "snapshot",
  getDataState: () => dataState,
  subscribeData: (listener) => { listeners.add(listener); return () => listeners.delete(listener); },
  getSnapshotState,
  subscribeSnapshot,
  refreshSnapshot: () => api.isSnapshot ? snapshotCall("refresh") : Promise.resolve(false),
  checkConnection: () => {
    if (mode !== "auto") return Promise.resolve(dataState.source === "api");
    if (!checking) checking = (async () => {
      try {
        const health = await request("/api/health", { timeout: 2500, cache: "no-store" });
        if (health?.status !== "ok" || health?.db !== "ok") throw new Error("Backend is not ready");
        useSource("api");
        return true;
      } catch {
        useSource("snapshot");
        return false;
      }
    })().finally(() => { checking = null; });
    return checking;
  },
  trigger: (body) => api.isSnapshot
    ? Promise.reject(Object.assign(new Error("当前使用只读快照，请连接本地后端后管理采集。"), { status: 405, code: "READ_ONLY" }))
    : request("/api/crawl/trigger", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
};
