import { expect, it } from 'vitest';
import { createReaderCache } from './reader-cache.js';
it('retains more than eight small shards and bounds total bytes', () => {
  const c=createReaderCache(100);
  for(let i=0;i<12;i++) c.set(String(i),i,5);
  expect(c.get('0')).toBe(0);
  c.set('large',9,60);
  expect(c.get('0')).toBe(0);
  expect(c.get('1')).toBeUndefined();
  c.set('oversized',1,101);
  expect(c.get('oversized')).toBeUndefined();
});
