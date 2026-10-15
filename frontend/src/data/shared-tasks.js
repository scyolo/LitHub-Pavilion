/** Reference-counted work: abort one consumer, not another page's shared asset. */
export const abortError = () => new DOMException('Request aborted', 'AbortError');
export function throwIfAborted(signal) { if (signal?.aborted) throw abortError(); }

export function waitFor(promise, signal) {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const abort = () => { cleanup(); reject(abortError()); };
    const cleanup = () => signal.removeEventListener('abort', abort);
    signal.addEventListener('abort', abort, { once: true });
    promise.then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); });
  });
}

export function createSharedTasks({ maxCached = 0, concurrency = 6 } = {}) {
  const pending = new Map(), cached = new Map(), queue = [];
  let running = 0;
  function settle(task, error, value) {
    if (error) task.controller.abort();
    if (pending.get(task.key) === task) pending.delete(task.key);
    if (!error && !task.controller.signal.aborted && maxCached > 0) {
      cached.delete(task.key); cached.set(task.key, value);
      while (cached.size > maxCached) cached.delete(cached.keys().next().value);
    }
    for (const consumer of task.consumers) {
      consumer.cleanup();
      if (error) consumer.reject(error); else consumer.resolve(value);
    }
    task.consumers.clear();
  }
  function pump() {
    while (running < concurrency && queue.length) {
      const task = queue.shift();
      if (task.controller.signal.aborted) continue;
      running++;
      Promise.resolve().then(() => {
        throwIfAborted(task.controller.signal);
        return task.load({ signal: task.controller.signal, onProgress: value => {
          for (const consumer of task.consumers) consumer.onProgress?.(value);
        } });
      }).then(value => settle(task, null, value), error => settle(task, error))
        .finally(() => { running--; pump(); });
    }
  }
  return {
    run(key, load, { signal, onProgress } = {}) {
      if (signal?.aborted) return Promise.reject(abortError());
      if (cached.has(key)) {
        const value = cached.get(key); cached.delete(key); cached.set(key, value);
        return Promise.resolve(value);
      }
      let task = pending.get(key);
      if (!task) {
        task = { key, load, controller: new AbortController(), consumers: new Set() };
        pending.set(key, task); queue.push(task);
      }
      return new Promise((resolve, reject) => {
        const cleanup = () => signal?.removeEventListener('abort', abort);
        const consumer = { resolve, reject, cleanup, onProgress };
        function abort() {
          task.consumers.delete(consumer); cleanup(); reject(abortError());
          if (!task.consumers.size) {
            if (pending.get(key) === task) pending.delete(key);
            const index = queue.indexOf(task);
            if (index >= 0) queue.splice(index, 1);
            task.controller.abort();
          }
        }
        task.consumers.add(consumer);
        signal?.addEventListener('abort', abort, { once: true });
        pump();
      });
    },
  };
}
