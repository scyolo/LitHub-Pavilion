// LRU bounded by encoded shard size, not just eight files. Parsed objects have
// additional engine overhead, so this is a payload budget, not a heap limit.
export function createReaderCache(maxBytes = 24 * 1024 * 1024) {
  const entries = new Map();
  let total = 0;
  return {
    has: key => entries.has(key),
    get(key) {
      const entry = entries.get(key);
      if (!entry) return undefined;
      entries.delete(key); entries.set(key, entry);
      return entry.value;
    },
    set(key, value, bytes) {
      if (entries.has(key)) { total -= entries.get(key).bytes; entries.delete(key); }
      if (!Number.isFinite(bytes) || bytes < 0 || bytes > maxBytes) return;
      entries.set(key, { value, bytes }); total += bytes;
      while (total > maxBytes) {
        const oldest = entries.keys().next().value;
        total -= entries.get(oldest).bytes; entries.delete(oldest);
      }
    },
  };
}
