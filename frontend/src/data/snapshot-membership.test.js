import { expect, it } from 'vitest';
import { createIdMembership } from './snapshot-membership.js';

const part = (min_id, max_id, count) => ({ min_id, max_id, count });

it('keeps legacy readers optional and handles empty snapshots', () => {
  expect(createIdMembership({ parts: [] }, 0)).toBe(null);
  const contains = createIdMembership({ parts: [], id_runs: [] }, 0);
  expect(contains(1)).toBe(false);
});

it('handles contiguous runs crossing part boundaries and preserves every gap', () => {
  const contains = createIdMembership({
    id_runs: [1, 5, 3, 2, 4, 1],
    parts: [part(1, 3, 3), part(4, 8, 3), part(9, 13, 2)],
  }, 8);
  for (let id = 0; id <= 14; id++) {
    expect(contains(id), String(id)).toBe([1, 2, 3, 4, 5, 8, 9, 13].includes(id));
  }
});

it('does not allocate by maximum ID and preserves safe-integer boundary IDs', () => {
  const max = Number.MAX_SAFE_INTEGER;
  const contains = createIdMembership({ id_runs: [1, 1, max - 1, 1], parts: [part(1, max, 2)] }, 2);
  expect(contains(1)).toBe(true);
  expect(contains(max)).toBe(true);
  expect(contains(max - 1)).toBe(false);
});

it.each([
  { id_runs: [1, 3], parts: [part(1, 3, 2)] },
  { id_runs: [1, 3], parts: [part(1, 2, 2)] },
  { id_runs: [1, 3], parts: [part(1, 2, 2), part(2, 3, 1)] },
  { id_runs: [1, 3], parts: [part(3, 3, 1), part(1, 2, 2)] },
  { id_runs: [1, 1, 3, 2], parts: [part(1, 4, 3)] },
])('rejects inconsistent per-part counts and boundaries: %j', ranking => {
  expect(() => createIdMembership(ranking, 3)).toThrow();
});
