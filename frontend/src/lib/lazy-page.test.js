import { afterEach, expect, it, vi } from 'vitest';
import { createPageModule } from './lazy-page.js';

afterEach(() => vi.useRealTimers());
it('reuses a prefetched route module when the user enters the sidebar page', async () => {
  const module = { default: () => null }, importer = vi.fn(async () => module);
  const page = createPageModule(importer);
  expect(await page.preload()).toBe(module);
  expect(await page.preload()).toBe(module);
  expect(importer).toHaveBeenCalledOnce();
});
it('retries a transient route-chunk failure once instead of caching the first rejection', async () => {
  vi.useFakeTimers();
  const module = { default: () => null };
  const importer = vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch dynamically imported module')).mockResolvedValue(module);
  const pending = createPageModule(importer).preload();
  await vi.advanceTimersByTimeAsync(400);
  expect(await pending).toBe(module); expect(importer).toHaveBeenCalledTimes(2);
});
it('keeps real module bugs visible and lets a later explicit preload recover', async () => {
  const importer = vi.fn().mockRejectedValueOnce(new SyntaxError('invalid source')).mockResolvedValue({ default: () => null });
  const page = createPageModule(importer);
  await expect(page.preload()).rejects.toThrow('invalid source');
  expect(importer).toHaveBeenCalledOnce();
  await page.preload(); expect(importer).toHaveBeenCalledTimes(2);
});
it('does not retry a broken deployment indefinitely', async () => {
  vi.useFakeTimers();
  const importer = vi.fn(async () => { throw new TypeError('Failed to fetch dynamically imported module'); });
  const check = expect(createPageModule(importer).preload()).rejects.toThrow('Failed to fetch');
  await vi.advanceTimersByTimeAsync(400); await check;
  expect(importer).toHaveBeenCalledTimes(2);
});
