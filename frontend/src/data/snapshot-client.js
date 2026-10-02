import { readerError } from "./snapshot-engine.js";

export const SNAPSHOT_REQUEST_TIMEOUT_MS = 12000;
let worker;
let nextId = 0;
const waiting = new Map();
const listeners = new Set();
let state = { status: "idle", revision: null, generation: 0, verification: null, generated_at: null, paper_count: null, loaded: 0, total: 0, error: null };

export function getSnapshotState() { return state; }
export function subscribeSnapshot(listener) { listeners.add(listener); return () => listeners.delete(listener); }
function setState(value) { state = value; for (const listener of listeners) listener(); }
function failWorker(error) {
  for (const request of waiting.values()) { request.cleanup(); request.reject(error); }
  waiting.clear(); worker?.terminate(); worker = null;
  setState({ ...state, status: "error", error: error.message });
}
function getWorker() {
  if (!worker) {
    const target = new Worker(new URL("./snapshot-worker.js", import.meta.url), { type: "module" });
    worker = target;
    target.addEventListener("message", ({ data }) => {
      if (worker !== target) return;
      if (data.type === "state") { setState(data.state); return; }
      const request = waiting.get(data.id);
      if (!request) return;
      waiting.delete(data.id); request.cleanup();
      if (data.error) request.reject(Object.assign(new Error(data.error.message), data.error));
      else request.resolve(data.result);
    });
    target.addEventListener("error", () => {
      if (worker === target) failWorker(readerError("本地检索模块加载失败，请刷新页面重试", 503, "READER_UNAVAILABLE"));
    });
  }
  return worker;
}

export function snapshotCall(method, params, signal) {
  if (signal?.aborted) return Promise.reject(new DOMException("Request aborted", "AbortError"));
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    let timer;
    function cleanup() { clearTimeout(timer); signal?.removeEventListener("abort", abort); }
    function abort() { waiting.delete(id); cleanup(); reject(new DOMException("Request aborted", "AbortError")); }
    try {
      const target = getWorker();
      signal?.addEventListener("abort", abort, { once: true });
      waiting.set(id, { resolve, reject, cleanup });
      // A blocked worker or several slow network stages must not leave a spinner
      // indefinitely. Termination also cancels its outstanding shard downloads.
      timer = setTimeout(() => {
        if (waiting.has(id)) failWorker(readerError("加载超过 12 秒，已停止等待。请检查网络后点击“重新加载”；也可增加来源或年份筛选。", 504, "SNAPSHOT_TIMEOUT"));
      }, SNAPSHOT_REQUEST_TIMEOUT_MS);
      target.postMessage({ id, method, params });
    } catch {
      waiting.delete(id); cleanup();
      const error = readerError("浏览器无法启动本地检索模块，请使用支持 Web Worker 的浏览器", 503, "READER_UNAVAILABLE");
      setState({ ...state, status: "error", error: error.message });
      reject(error);
    }
  });
}
