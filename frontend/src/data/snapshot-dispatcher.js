import { waitFor } from './shared-tasks.js';

/** Keep request ownership separate from the store's revision-bound shared cache. */
export function createSnapshotDispatcher(store, postMessage) {
  const requests = new Map();
  return async function dispatch(data) {
    if (data.type === 'cancel') {
      requests.get(data.id)?.abort();
      postMessage({ type: 'cancelled', id: data.id });
      return;
    }
    const controller = new AbortController();
    requests.set(data.id, controller);
    let lastProgress = -Infinity;
    const progress = () => {
      const now = performance.now();
      if (!controller.signal.aborted && now - lastProgress >= 200) {
        lastProgress = now; postMessage({ type: 'progress', id: data.id });
      }
    };
    try {
      const result = data.method === 'refresh'
        ? await waitFor(store.refresh(), controller.signal)
        : await store.call(data.method, data.params, controller.signal, progress);
      if (!controller.signal.aborted) postMessage({ id: data.id, result });
    } catch (error) {
      if (!controller.signal.aborted) {
        controller.abort();
        postMessage({ id: data.id, error: { message: error.message, name: error.name, status: error.status, code: error.code } });
      }
    } finally {
      if (requests.get(data.id) === controller) requests.delete(data.id);
    }
  };
}
