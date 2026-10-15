import { expect, it, vi } from 'vitest';
import { createSharedTasks } from './shared-tasks.js';

const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

it('shares a load, relays progress, and cancels only the abandoned consumer', async () => {
  const tasks = createSharedTasks({ maxCached: 2 });
  const ready = deferred(), first = new AbortController(), progress = vi.fn();
  let context;
  const load = vi.fn(async value => { context = value; return ready.promise; });
  const one = tasks.run('asset', load, { signal: first.signal });
  const check = expect(one).rejects.toMatchObject({ name: 'AbortError' });
  const two = tasks.run('asset', load, { onProgress: progress });
  await flush(); first.abort(); await check;
  expect(context.signal.aborted).toBe(false);
  context.onProgress({ loaded: 1 }); expect(progress).toHaveBeenCalledWith({ loaded: 1 });
  ready.resolve('verified'); expect(await two).toBe('verified');
  expect(await tasks.run('asset', load)).toBe('verified'); expect(load).toHaveBeenCalledOnce();
});

it('aborts unused work and never attaches a new reader to an aborted promise', async () => {
  const tasks = createSharedTasks();
  const controller = new AbortController(); let oldSignal;
  const old = tasks.run('asset', ({ signal }) => new Promise((resolve, reject) => {
    oldSignal = signal; signal.addEventListener('abort', () => reject(signal.reason), { once: true });
  }), { signal: controller.signal });
  const check = expect(old).rejects.toMatchObject({ name: 'AbortError' });
  await flush(); controller.abort(); await check;
  expect(oldSignal.aborted).toBe(true);
  expect(await tasks.run('asset', async () => 'new')).toBe('new');
});

it('bounds concurrent downloads across callers and drops cancelled queued work', async () => {
  const tasks = createSharedTasks({ concurrency: 2 });
  const ready = deferred(), queued = new AbortController(); let running = 0, maximum = 0;
  const load = vi.fn(async () => { maximum = Math.max(maximum, ++running); await ready.promise; running--; return 'ok'; });
  const first = tasks.run('one', load), second = tasks.run('two', load);
  const cancelled = tasks.run('three', load, { signal: queued.signal });
  const check = expect(cancelled).rejects.toMatchObject({ name: 'AbortError' });
  const last = tasks.run('four', load);
  await flush(); expect(load).toHaveBeenCalledTimes(2); queued.abort(); await check;
  ready.resolve(); await Promise.all([first, second, last]);
  expect(maximum).toBe(2); expect(load).toHaveBeenCalledTimes(3);
});

it('does not cache failures and evicts least recently used results', async () => {
  const tasks = createSharedTasks({ maxCached: 2 });
  await expect(tasks.run('bad', async () => { throw new Error('network'); })).rejects.toThrow('network');
  expect(await tasks.run('bad', async () => 'recovered')).toBe('recovered');
  const load = vi.fn(async () => 'result');
  await tasks.run('a', load); await tasks.run('bad', load); await tasks.run('b', load);
  await tasks.run('bad', load); await tasks.run('a', load);
  expect(load).toHaveBeenCalledTimes(3);
});

it('does not start a task for an already cancelled caller', async () => {
  const controller = new AbortController(); controller.abort(); const load = vi.fn();
  await expect(createSharedTasks().run('x', load, { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' });
  expect(load).not.toHaveBeenCalled();
});
