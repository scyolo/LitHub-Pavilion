import { createSnapshotEngine, readerError } from "./snapshot-engine.js";
import { createOverview } from "./snapshot-overview.js";

const MAX_FILE_BYTES = 8 * 1024 * 1024;
const MAX_TOTAL_BYTES = 800 * 1024 * 1024;
const invalid = () => readerError("静态快照不完整或校验失败，请稍后重新检查更新", 503, "INVALID_SNAPSHOT");
const canonical = (value) => value && typeof value === "object" ? Array.isArray(value) ? value.map(canonical) : Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])])) : value;
const serialize = (value) => JSON.stringify(canonical(value));

async function validateManifest(manifest) {
  if (!manifest || Object.keys(manifest).sort().join() !== ["schema_version", "revision", "generated_at", "paper_count", "catalog", "chunks"].sort().join() || manifest.schema_version !== 1 || !/^[0-9a-f]{64}$/.test(manifest.revision) || !Number.isFinite(Date.parse(manifest.generated_at)) || !Number.isSafeInteger(manifest.paper_count) || manifest.paper_count < 0 || !Array.isArray(manifest.chunks) || manifest.chunks.length > 4096) throw invalid();
  for (const [entry, prefix] of [[manifest.catalog, "catalog"], ...manifest.chunks.map((chunk) => [chunk, "papers"])]) {
    if (!entry || !/^[0-9a-f]{64}$/.test(entry.sha256) || entry.path !== `${prefix}-${entry.sha256}.json` || Object.keys(entry).length !== (prefix === "papers" ? 3 : 2)) throw invalid();
    if (prefix === "papers" && (!Number.isSafeInteger(entry.count) || entry.count < 1)) throw invalid();
  }
  if (manifest.chunks.reduce((sum, chunk) => sum + chunk.count, 0) !== manifest.paper_count) throw invalid();
  const { schema_version, paper_count, catalog, chunks } = manifest;
  await verifyDigest(new TextEncoder().encode(serialize({ schema_version, paper_count, catalog, chunks })), manifest.revision);
}

async function verifyDigest(bytes, expected) {
  if (!globalThis.crypto?.subtle) throw readerError("浏览器需要 HTTPS 或本机安全地址才能校验快照", 503, "SECURE_CONTEXT_REQUIRED");
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const actual = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  if (actual !== expected) throw invalid();
}

export function createSnapshotStore({ baseUrl, fetcher = globalThis.fetch.bind(globalThis), onState = () => {} }) {
  const base = new URL(baseUrl);
  let active = null, pending = null, wantFull = false;
  let state = { status: "idle", revision: null, generation: 0, verification: null, generated_at: null, paper_count: null, loaded: 0, total: 0, error: null };
  function update(values) { state = { ...state, ...values }; onState(state); }
  async function download(path, digest, cache, maxBytes = MAX_FILE_BYTES, batchSignal) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    batchSignal?.addEventListener("abort", abort, { once: true });
    if (batchSignal?.aborted) abort();
    const timeout = setTimeout(abort, 45000);
    try {
      const response = await fetcher(new URL(path, base).href, { cache, mode: "same-origin", credentials: "omit", redirect: "error", signal: controller.signal });
      if (!response.ok) throw readerError(path === "manifest.json" && response.status === 404 ? "尚未发布论文快照。请在本地导出数据并完成首次发布。" : "快照文件暂时不可用，请稍后重试", 503, "SNAPSHOT_UNAVAILABLE");
      let bytes;
      if (response.body?.getReader) {
        const reader = response.body.getReader();
        const chunks = []; let size = 0;
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > maxBytes) { await reader.cancel(); throw invalid(); }
          chunks.push(value);
        }
        bytes = new Uint8Array(size); let offset = 0;
        for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
      } else {
        bytes = new TextEncoder().encode(await response.text());
      }
      if (bytes.byteLength > maxBytes) throw invalid();
      if (digest) await verifyDigest(bytes, digest);
      let data;
      try { data = JSON.parse(new TextDecoder().decode(bytes)); } catch { throw invalid(); }
      return { data, size: bytes.byteLength };
    } finally {
      clearTimeout(timeout);
      batchSignal?.removeEventListener("abort", abort);
    }
  }
  async function complete(candidate) {
    if (candidate.engine) return candidate;
    const { manifest, catalog } = candidate;
    update({ status: active ? "updating" : "loading", total: manifest.chunks.length + 1, loaded: 1 });
    let totalBytes = candidate.bytes, cursor = 0, loaded = 1, failure;
    const groups = new Array(manifest.chunks.length);
    const batch = new AbortController();
    await Promise.all(Array.from({ length: Math.min(4, manifest.chunks.length) }, async () => {
      try {
        while (!batch.signal.aborted && cursor < manifest.chunks.length) {
          const index = cursor++, entry = manifest.chunks[index];
          const result = await download(entry.path, entry.sha256, "default", MAX_FILE_BYTES, batch.signal);
          totalBytes += result.size;
          if (totalBytes > MAX_TOTAL_BYTES || !Array.isArray(result.data) || result.data.length !== entry.count) throw invalid();
          groups[index] = result.data;
          if (!batch.signal.aborted) update({ loaded: ++loaded });
        }
      } catch (error) { failure ||= error; batch.abort(); }
    }));
    if (failure) throw failure;
    const engine = createSnapshotEngine({ manifest, catalog, papers: groups.flat() });
    if (candidate.overview) {
      for (const scope of catalog.overview.scopes) {
        const { generated_at, last_crawl, ...dashboard } = engine.dashboard({ level: scope.level, type: scope.type });
        if (serialize(dashboard) !== serialize(scope.dashboard) || serialize(engine.latest({ level: scope.level, type: scope.type }).items) !== serialize(scope.latest)) throw invalid();
      }
    }
    return { ...candidate, engine };
  }
  function commit(candidate) {
    const generation = state.generation + Number(Boolean(active && active.manifest.revision !== candidate.manifest.revision));
    active = candidate;
    update({ status: "ready", revision: candidate.manifest.revision, generation, verification: candidate.engine ? "full" : "catalog", generated_at: candidate.manifest.generated_at, paper_count: candidate.manifest.paper_count, error: null });
  }
  function run(operation) {
    if (!pending) pending = operation().catch((error) => {
      update({ status: active ? "ready" : "error", error: error.name === "AbortError" ? "下载快照超时，请重试。" : error.message || "无法读取快照" });
      throw error;
    }).finally(() => { pending = null; });
    return pending;
  }
  function refresh() {
    return run(async () => {
      update({ status: active ? "updating" : "loading", error: null, loaded: 0, total: 1 });
      const { data: manifest } = await download("manifest.json", null, "no-cache", 1024 * 1024);
      await validateManifest(manifest);
      if (active?.manifest.revision === manifest.revision) { update({ status: "ready" }); return false; }
      const { data: catalog, size } = await download(manifest.catalog.path, manifest.catalog.sha256, "default");
      let candidate = { manifest, catalog, bytes: size, overview: createOverview({ manifest, catalog }), engine: null };
      if (!candidate.overview || wantFull || active?.engine) candidate = await complete(candidate);
      commit(candidate);
      return true;
    });
  }
  async function load() {
    wantFull = true;
    if (!active) await refresh();
    if (!active.engine) {
      if (pending) await pending;
      if (!active.engine) await run(async () => { commit(await complete(active)); });
    }
    return active.manifest;
  }
  async function call(method, params, signal) {
    if (signal?.aborted) throw new DOMException("Request aborted", "AbortError");
    const lightweight = ["dashboard", "latest", "directions", "venues", "stats", "crawlLogs", "crawlStatus"].includes(method);
    if (!lightweight) wantFull = true;
    if (!active) await refresh();
    if (!(active.overview?.supports(method, params)) && !active.engine) await load();
    if (signal?.aborted) throw new DOMException("Request aborted", "AbortError");
    const engine = active.overview?.supports(method, params) ? active.overview : active.engine;
    if (typeof engine?.[method] !== "function") throw readerError("不支持的只读操作", 405);
    return engine[method](params);
  }
  return { load, refresh, call, getState: () => state };
}
