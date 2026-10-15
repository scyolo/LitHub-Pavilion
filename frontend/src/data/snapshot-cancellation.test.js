import { afterEach, beforeEach, expect, it, vi } from 'vitest';

let instances;
beforeEach(() => {
  vi.resetModules(); vi.useFakeTimers(); instances = [];
  vi.stubGlobal('Worker', class {
    handlers = new Map(); postMessage = vi.fn(); terminate = vi.fn();
    constructor() { instances.push(this); }
    addEventListener(name, fn) { this.handlers.set(name, fn); }
    reply(data) { this.handlers.get('message')({ data }); }
  });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it('forwards navigation cancellation to the worker', async () => {
  const { snapshotCall } = await import('./snapshot-client.js');
  const controller = new AbortController();
  const pending = snapshotCall('search', { q: 'old query' }, controller.signal);
  const check = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  const id = instances[0].postMessage.mock.calls[0][0].id;
  controller.abort(); await check;
  expect(instances[0].postMessage).toHaveBeenCalledWith({ type: 'cancel', id });
  instances[0].reply({ type: 'cancelled', id });
  expect(vi.getTimerCount()).toBe(0);
});

it('does not terminate a live worker or fail a new page when an old request times out', async () => {
  const { snapshotCall } = await import('./snapshot-client.js');
  const old = snapshotCall('search', { q: 'blocked' });
  const oldCheck = expect(old).rejects.toMatchObject({ code: 'SNAPSHOT_TIMEOUT' });
  const id = instances[0].postMessage.mock.calls[0][0].id;
  await vi.advanceTimersByTimeAsync(11000);
  const next = snapshotCall('papers', { direction: 'llm' });
  const nextCheck = expect(next).resolves.toEqual({ total: 42 });
  nextCheck.catch(() => {});
  const nextId = instances[0].postMessage.mock.calls.at(-1)[0].id;
  await vi.advanceTimersByTimeAsync(1000); await oldCheck;
  expect(instances[0].terminate).not.toHaveBeenCalled();
  instances[0].reply({ type: 'cancelled', id });
  instances[0].reply({ id: nextId, result: { total: 42 } }); await nextCheck;
  expect(vi.getTimerCount()).toBe(0);
});

it('allows a slow download making real progress, but keeps an absolute deadline', async () => {
  const client = await import('./snapshot-client.js');
  const pending = client.snapshotCall('search', { q: 'learning' });
  const check = expect(pending).resolves.toEqual({ total: 7 });
  check.catch(() => {});
  const id = instances[0].postMessage.mock.calls[0][0].id;
  await vi.advanceTimersByTimeAsync(10000);
  instances[0].reply({ type: 'progress', id, loaded: 100 });
  await vi.advanceTimersByTimeAsync(10000);
  instances[0].reply({ id, result: { total: 7 } }); await check;
  expect(instances[0].terminate).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});

it('caps waiting even if a worker keeps sending progress', async () => {
  const client = await import('./snapshot-client.js');
  const pending = client.snapshotCall('search', { q: 'endless' });
  const check = expect(pending).rejects.toMatchObject({ code: 'SNAPSHOT_TIMEOUT' });
  check.catch(() => {});
  const id = instances[0].postMessage.mock.calls[0][0].id;
  for (let elapsed = 10000; elapsed < 60000; elapsed += 10000) {
    await vi.advanceTimersByTimeAsync(10000);
    instances[0].reply({ type: 'progress', id, loaded: elapsed });
  }
  await vi.advanceTimersByTimeAsync(10000); await check;
  instances[0].reply({ type: 'cancelled', id });
  expect(vi.getTimerCount()).toBe(0);
});
