import { createSnapshotEngine, readerError } from "./snapshot-engine.js";

const MAX_FILE_BYTES = 8 * 1024 * 1024;
const MAX_TOTAL_BYTES = 800 * 1024 * 1024;
const invalid = () => readerError("静态快照不完整或校验失败，请稍后重新检查更新", 503, "INVALID_SNAPSHOT");

function validateManifest(manifest) {
  if (!manifest || manifest.schema_version !== 1 || !/^[0-9a-f]{64}$/.test(manifest.revision) || !Number.isFinite(Date.parse(manifest.generated_at)) || !Number.isSafeInteger(manifest.paper_count) || manifest.paper_count < 0 || !Array.isArray(manifest.chunks) || manifest.chunks.length > 4096) throw invalid();
  for (const [entry, prefix] of [[manifest.catalog, "catalog"], ...manifest.chunks.map((chunk) => [chunk, "papers"])]) {
    if (!entry || !/^[0-9a-f]{64}$/.test(entry.sha256) || entry.path !== `${prefix}-${entry.sha256}.json`) throw invalid();
    if (prefix === "papers" && (!Number.isSafeInteger(entry.count) || entry.count < 1)) throw invalid();
  }
  if (manifest.chunks.reduce((sum, chunk) => sum + chunk.count, 0) !== manifest.paper_count) throw invalid();
}

async function verifyDigest(bytes, expected) {
  if (!globalThis.crypto?.subtle) throw readerError("浏览器需要 HTTPS 或本机安全地址才能校验快照", 503, "SECURE_CONTEXT_REQUIRED");
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const actual = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  if (actual !== expected) throw invalid();
}

export function createSnapshotStore({ baseUrl, fetcher = globalThis.fetch.bind(globalThis), onState = () => {} }) {
  const base = new URL(baseUrl);
  let engine = null, manifest = null, pending = null;
  let state = { status: "idle", revision: null, generated_at: null, paper_count: null, loaded: 0, total: 0, error: null };
  function update(values) { state = { ...state, ...values }; onState(state); }
  async function download(path, digest, cache, maxBytes = MAX_FILE_BYTES) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 45000);
    try {
      const response = await fetcher(new URL(path, base).href, { cache, credentials: "omit", redirect: "error", signal: controller.signal });
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
    } finally { clearTimeout(timeout); }
  }
  async function updateSnapshot() {
    update({ status: engine ? "updating" : "loading", error: null, loaded: 0 });
    try {
      const { data: next } = await download("manifest.json", null, "no-cache", 1024 * 1024);
      validateManifest(next);
      if (manifest?.revision === next.revision) { update({ status: "ready" }); return false; }
      update({ total: next.chunks.length + 1 });
      const { data: catalog, size } = await download(next.catalog.path, next.catalog.sha256, "default");
      let totalBytes = size, cursor = 0, loaded = 1;
      update({ loaded });
      const groups = new Array(next.chunks.length);
      await Promise.all(Array.from({ length: Math.min(4, next.chunks.length) }, async () => {
        while (cursor < next.chunks.length) {
          const index = cursor++, entry = next.chunks[index];
          const result = await download(entry.path, entry.sha256, "default");
          totalBytes += result.size;
          if (totalBytes > MAX_TOTAL_BYTES || !Array.isArray(result.data) || result.data.length !== entry.count) throw invalid();
          groups[index] = result.data;
          update({ loaded: ++loaded });
        }
      }));
      const candidate = createSnapshotEngine({ manifest: next, catalog, papers: groups.flat() });
      engine = candidate; manifest = next;
      update({ status: "ready", revision: next.revision, generated_at: next.generated_at, paper_count: next.paper_count, error: null });
      return true;
    } catch (error) {
      update({ status: engine ? "ready" : "error", error: error.name === "AbortError" ? "下载快照超时，请重试。" : error.message || "无法读取快照" });
      throw error;
    }
  }
  function refresh() {
    if (!pending) pending = updateSnapshot().finally(() => { pending = null; });
    return pending;
  }
  async function load() { if (!engine) await refresh(); return manifest; }
  async function call(method, params, signal) {
    if (signal?.aborted) throw new DOMException("Request aborted", "AbortError");
    await load();
    if (signal?.aborted) throw new DOMException("Request aborted", "AbortError");
    if (typeof engine[method] !== "function") throw readerError("不支持的只读操作", 405);
    return engine[method](params);
  }
  return { load, refresh, call, getState: () => state };
}
