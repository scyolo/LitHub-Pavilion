import { readerError } from './reader-errors.js';

const invalid = () => readerError('会议关联索引校验失败，请重新导出', 503, 'INVALID_SNAPSHOT');
export const includesAssociated = filters => [true, 1, '1', 'true'].includes(filters.include_associated);

export function createConferenceScope(catalog) {
  const venues = new Map(catalog.venues.map(v => [v.abbr, v]));
  const value = catalog.conference_associations ?? {};
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid();
  const members = new Map(), ordered = new Map();
  for (const [abbr, years] of Object.entries(value)) {
    if (venues.get(abbr)?.type !== 'conf' || !['A', 'B'].includes(venues.get(abbr)?.level) || !years || typeof years !== 'object' || Array.isArray(years)) throw invalid();
    const ids = new Set();
    for (const [year, entries] of Object.entries(years)) {
      if (!/^[0-9]{4}$/.test(year) || Number(year) < 2000 || Number(year) > 2100 || !Array.isArray(entries) || !entries.length) throw invalid();
      let previous = 0;
      for (const id of entries) {
        if (!Number.isSafeInteger(id) || id <= previous) throw invalid();
        previous = id; ids.add(id);
      }
    }
    members.set(abbr, ids);
    ordered.set(abbr, [...ids].sort((a, b) => a - b));
  }
  const scopeMatches = (v, filters) => Boolean(v) && (!filters.level || v.level === filters.level) && (!filters.type || v.type === filters.type);
  function matches(id, canonical, filters) {
    if (includesAssociated(filters) && filters.venue) {
      return scopeMatches(venues.get(filters.venue), filters)
        && (canonical === filters.venue || Boolean(members.get(filters.venue)?.has(id)));
    }
    return (!filters.venue || filters.venue === canonical) && scopeMatches(venues.get(canonical), filters);
  }
  function shardMatches(entry, filters) {
    if (includesAssociated(filters) && filters.venue) {
      if (!scopeMatches(venues.get(filters.venue), filters)) return false;
      if (entry.venues.includes(filters.venue)) return true;
      const ids = ordered.get(filters.venue) || [];
      let low = 0, high = ids.length;
      while (low < high) { const middle = (low + high) >>> 1; if (ids[middle] < entry.min_id) low = middle + 1; else high = middle; }
      return low < ids.length && ids[low] <= entry.max_id;
    }
    return entry.venues.some(name => (!filters.venue || filters.venue === name) && scopeMatches(venues.get(name), filters));
  }
  function decorate(values, admitted = () => true) {
    return values.map(venue => {
      const count = [...(members.get(venue.abbr) || [])].filter(admitted).length;
      return count ? {...venue, associated_paper_count: count} : venue;
    });
  }
  return {matches, shardMatches, decorate};
}
