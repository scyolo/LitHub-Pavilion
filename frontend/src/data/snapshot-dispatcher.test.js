import { expect, it, vi } from 'vitest';
import { createSnapshotDispatcher } from './snapshot-dispatcher.js';

it('aborts a worker request without rejecting another active page', async () => {
  const signals = new Map(), reply = vi.fn();
  const store = { call: vi.fn((method, params, signal) => {
    signals.set(params.q, signal);
    return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }));
  }) };
  const dispatch = createSnapshotDispatcher(store, reply);
  const old = dispatch({ id: 1, method: 'search', params: { q: 'old' } });
  const next = dispatch({ id: 2, method: 'search', params: { q: 'next' } });
  await dispatch({ type: 'cancel', id: 1 }); await old;
  expect(signals.get('old').aborted).toBe(true);
  expect(signals.get('next').aborted).toBe(false);
  expect(reply).toHaveBeenCalledWith({ type: 'cancelled', id: 1 });
  expect(reply.mock.calls.some(([data]) => data.id === 1 && data.error)).toBe(false);
  await dispatch({ type: 'cancel', id: 2 }); await next;
});

it('tags actual download progress with the consumer id and leaves data errors visible', async () => {
  const reply = vi.fn();
  const store = { call: vi.fn(async (method, params, signal, progress) => {
    progress({ loaded: 42 });
    throw Object.assign(new Error('bad hash'), { status: 503, code: 'INVALID_SNAPSHOT' });
  }) };
  await createSnapshotDispatcher(store, reply)({ id: 3, method: 'papers', params: {} });
  expect(reply).toHaveBeenCalledWith(expect.objectContaining({ type: 'progress', id: 3 }));
  expect(reply).toHaveBeenCalledWith({ id: 3, error: expect.objectContaining({ code: 'INVALID_SNAPSHOT' }) });
});
