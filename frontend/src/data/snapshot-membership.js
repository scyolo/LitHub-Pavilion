import { readerError } from "./reader-errors.js";

const invalid = () => readerError("论文身份索引校验失败，请重新发布快照", 503, "INVALID_SNAPSHOT");

/** Decode optional, revision-bound exact ID runs; never allocate by maximum ID. */
export function createIdMembership(ranking, paperCount) {
  if (!("id_runs" in ranking)) return null;
  const runs = ranking.id_runs;
  if (!Array.isArray(runs) || runs.length % 2 || runs.length > paperCount * 2) throw invalid();
  const ranges = new Float64Array(runs.length);
  let previous = 0, total = 0;
  for (let i = 0; i < runs.length; i += 2) {
    const gap = runs[i], length = runs[i + 1];
    if (!Number.isSafeInteger(gap) || gap < (i ? 2 : 1)
        || !Number.isSafeInteger(length) || length < 1) throw invalid();
    const start = previous + gap, end = start + (length - 1);
    total += length;
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end)
        || !Number.isSafeInteger(total) || total > paperCount) throw invalid();
    ranges[i] = start; ranges[i + 1] = end; previous = end;
  }
  if (total !== paperCount) throw invalid();
  function contains(id) {
    let low = 0, high = ranges.length / 2;
    while (low < high) {
      const mid = (low + high) >>> 1;
      if (ranges[mid * 2 + 1] < id) low = mid + 1;
      else high = mid;
    }
    return low * 2 < ranges.length && ranges[low * 2] <= id;
  }
  // Check exact per-part counts/bounds too, in a single pass over sorted ranges.
  let cursor = 0, lastMax = 0, matched = 0;
  for (const part of ranking.parts) {
    if (part.min_id <= lastMax || !contains(part.min_id) || !contains(part.max_id)) throw invalid();
    while (cursor < ranges.length && ranges[cursor + 1] < part.min_id) cursor += 2;
    let count = 0;
    for (; cursor < ranges.length && ranges[cursor] <= part.max_id; cursor += 2) {
      count += Math.min(ranges[cursor + 1], part.max_id) - Math.max(ranges[cursor], part.min_id) + 1;
      if (ranges[cursor + 1] > part.max_id) break;
    }
    if (count !== part.count) throw invalid();
    matched += count; lastMax = part.max_id;
  }
  if (matched !== paperCount) throw invalid();
  return contains;
}
