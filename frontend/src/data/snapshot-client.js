import { readerError } from './reader-errors.js';

// An idle deadline catches broken downloads; progress may extend a slow read,
// but never beyond the absolute cap. Neither deadline kills another page.
export const SNAPSHOT_REQUEST_TIMEOUT_MS = 12000;
export const SNAPSHOT_MAX_WAIT_MS = 60000;
let worker, nextId = 0, activity = 0;
const waiting = new Map(), cancellations = new Map(), listeners = new Set();
let state = { status: 'idle', revision: null, generation: 0, verification: null, generated_at: null, paper_count: null, loaded: 0, total: 0, error: null };

export function getSnapshotState() { return state; }
export function subscribeSnapshot(listener) { listeners.add(listener); return () => listeners.delete(listener); }
function setState(value) { state = value; for (const listener of listeners) listener(); }
function clearCancellation(id) { clearTimeout(cancellations.get(id)); cancellations.delete(id); }
function failWorker(error) {
  for (const request of waiting.values()) { request.cleanup(); request.reject(error); }
  waiting.clear();
  for (const id of cancellations.keys()) clearCancellation(id);
  worker?.terminate(); worker = null;
  setState({ ...state, status: state.revision ? 'ready' : 'error', error: error.message });
}
function cancel(target, id) {
  const seen = activity;
  target.postMessage({ type: 'cancel', id });
  cancellations.set(id, setTimeout(() => {
    cancellations.delete(id);
    // A truly wedged worker cannot acknowledge cancellation. Reclaim it only
    // when no other consumer needs it and no subsequent message proves it alive.
    if (worker === target && !waiting.size && activity === seen) { target.terminate(); worker = null; }
  }, 1000));
}
function getWorker() {
  if (!worker) {
    const target = new Worker(new URL('./snapshot-worker.js', import.meta.url), { type: 'module' });
    worker = target;
    target.addEventListener('message', ({ data }) => {
      if (worker !== target) return;
      activity++;
      if (data.type === 'state') {
        const revision = data.state.revision || state.revision;
        const generation = state.generation + Number(Boolean(revision && state.revision && revision !== state.revision));
        setState({ ...data.state, revision, generation }); return;
      }
      if (data.type === 'cancelled') { clearCancellation(data.id); return; }
      const request = waiting.get(data.id);
      if (!request) return;
      if (data.type === 'progress') { request.progress(); return; }
      waiting.delete(data.id); request.cleanup();
      if (data.error) request.reject(Object.assign(new Error(data.error.message), data.error));
      else {
        if (state.error) setState({ ...state, error: null, status: state.revision ? 'ready' : state.status });
        request.resolve(data.result);
      }
    });
    target.addEventListener('error', () => {
      if (worker === target) failWorker(readerError('本地检索模块加载失败，请刷新页面重试', 503, 'READER_UNAVAILABLE'));
    });
  }
  return worker;
}

export function snapshotCall(method, params, signal) {
  if (signal?.aborted) return Promise.reject(new DOMException('Request aborted', 'AbortError'));
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    let idleTimer, hardTimer, target;
    function cleanup() { clearTimeout(idleTimer); clearTimeout(hardTimer); signal?.removeEventListener('abort', abort); }
    function abort() {
      waiting.delete(id); cleanup();
      if (target === worker) cancel(target, id);
      reject(new DOMException('Request aborted', 'AbortError'));
    }
    function timeout() {
      if (!waiting.has(id)) return;
      waiting.delete(id); cleanup(); cancel(target, id);
      const error = readerError('读取长时间没有进展或超过等待上限，已停止本次请求。可点击“重新加载”，或切换来源、年份与方向；其他页面不受影响。', 504, 'SNAPSHOT_TIMEOUT');
      if (!waiting.size) setState({ ...state, status: state.revision ? 'ready' : 'error', error: error.message });
      reject(error);
    }
    function progress() { clearTimeout(idleTimer); idleTimer = setTimeout(timeout, SNAPSHOT_REQUEST_TIMEOUT_MS); }
    try {
      target = getWorker();
      signal?.addEventListener('abort', abort, { once: true });
      waiting.set(id, { resolve, reject, cleanup, progress });
      progress(); hardTimer = setTimeout(timeout, SNAPSHOT_MAX_WAIT_MS);
      target.postMessage({ id, method, params });
    } catch {
      waiting.delete(id); cleanup();
      const error = readerError('浏览器无法启动本地检索模块，请使用支持 Web Worker 的浏览器', 503, 'READER_UNAVAILABLE');
      setState({ ...state, status: 'error', error: error.message }); reject(error);
    }
  });
}
