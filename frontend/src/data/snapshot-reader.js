import { createSharedTasks, throwIfAborted } from "./shared-tasks.js";
import { createRankedReader } from "./snapshot-ranked.js";
import { createReaderCache } from "./reader-cache.js";
import { expandTokens } from "./fuzzy-terms.js";
import { createSnapshotEngine, normalizedTitle, queryTokens, parseParams, readerError } from "./snapshot-engine.js";

const fields = ["id", "title", "venue", "year", "publication_date", "created_at", "citation_count", "directions", "venue_confirmed", "doi", "official_url", "oa_url", "first_author", "authors_count", "pdf_status", "pdf_source"];
const invalid = () => readerError("轻量索引校验失败，请重新发布快照", 503, "INVALID_SNAPSHOT");

export function createLazyReader({ manifest, catalog, download, onProgress = () => {} }) {
  const descriptor = catalog.reader;
  if (!descriptor || typeof DecompressionStream === "undefined") return null;
  if ([4, 6].includes(descriptor.version)) {
    const entry = descriptor.index;
    if (descriptor.paper_count !== manifest.paper_count || !entry || !/^[0-9a-f]{64}$/.test(entry.sha256) || entry.path !== `reader-${entry.sha256}.json.gz` || entry.count !== manifest.paper_count) throw invalid();
    const loading = createSharedTasks({ maxCached: 1 });
    return { async call(method, params, context = {}) {
      const reader = await loading.run("index", async shared => {
        const { data } = await download(entry.path, entry.sha256, "force-cache", undefined, shared.signal, shared.onProgress);
        if (data?.version !== (descriptor.version === 6 ? 5 : 3) || data.paper_count !== manifest.paper_count) throw invalid();
        return createLazyReader({ manifest, catalog: { ...catalog, reader: data }, download, onProgress });
      }, context);
      throwIfAborted(context.signal);
      return reader.call(method, params, context);
    } };
  }

  if (![1, 2, 3, 5].includes(descriptor.version) || descriptor.paper_count !== manifest.paper_count || JSON.stringify(descriptor.fields) !== JSON.stringify(fields) || !Array.isArray(descriptor.browse) || !Array.isArray(descriptor.details) || descriptor.details.length !== manifest.chunks.length) throw invalid();
  for (const [entries, prefix] of [[descriptor.browse, "browse"], [descriptor.details, "compressed"]]) {
    if (entries.length > 4096 || entries.reduce((sum, entry) => sum + entry.count, 0) !== manifest.paper_count) throw invalid();
    entries.forEach((entry, index) => {
      if (!/^[0-9a-f]{64}$/.test(entry.sha256) || entry.path !== `${prefix}-${entry.sha256}.json.gz` || !Number.isSafeInteger(entry.count) || entry.count < 1) throw invalid();
      if (prefix === "compressed" && (entry.sha256 !== manifest.chunks[index].sha256 || entry.count !== manifest.chunks[index].count || !Number.isSafeInteger(entry.min_id) || !Number.isSafeInteger(entry.max_id) || entry.min_id < 1 || entry.max_id < entry.min_id || !Array.isArray(entry.venues) || !Array.isArray(entry.years) || !Array.isArray(entry.directions))) throw invalid();
    });
  }
  if (descriptor.version >= 2) {
    if (descriptor.version >= 5 && descriptor.search?.bucket_chars !== 3) throw invalid();
    if (descriptor.search?.version !== (descriptor.version >= 5 ? 3 : descriptor.version >= 3 ? 2 : 1) || !Number.isFinite(descriptor.search.average_length) || descriptor.search.average_length <= 0) throw invalid();
    for (const [section, prefix] of [["terms", "search"], ["titles", "titles"]]) {
      const buckets = descriptor.search[section];
      if (!buckets || typeof buckets !== "object" || Array.isArray(buckets) || Object.keys(buckets).length > (section === "terms" && descriptor.version >= 5 ? 4096 : 256)) throw invalid();
      for (const [bucket, entries] of Object.entries(buckets)) {
        if (!(section === "terms" && descriptor.version >= 5 ? /^[0-9a-f]{3}$/ : /^[0-9a-f]{2}$/).test(bucket) || !Array.isArray(entries) || entries.length > 4096) throw invalid();
        for (const entry of entries) if (!/^[0-9a-f]{64}$/.test(entry.sha256) || entry.path !== `${prefix}-${entry.sha256}.json.gz` || !Number.isSafeInteger(entry.count) || entry.count < 1) throw invalid();
      }
    }
    if (descriptor.version >= 3) {
      if (!Array.isArray(descriptor.search.vocabulary) || descriptor.search.vocabulary.length > 32) throw invalid();
      for (const entry of descriptor.search.vocabulary) if (!/^[0-9a-f]{64}$/.test(entry.sha256) || entry.path !== `vocabulary-${entry.sha256}.json.gz` || !Number.isSafeInteger(entry.count) || entry.count < 1) throw invalid();
    }
    for (const entry of descriptor.browse) if (!Number.isSafeInteger(entry.min_id) || !Number.isSafeInteger(entry.max_id) || entry.min_id < 1 || entry.min_id > entry.max_id) throw invalid();
  }
  if (descriptor.browse_chunk_size !== undefined && (!Number.isSafeInteger(descriptor.browse_chunk_size)
      || descriptor.browse_chunk_size < 1 || descriptor.browse_chunk_size > 4096
      || descriptor.browse.some(entry => entry.count > descriptor.browse_chunk_size))) throw invalid();
  const venues = new Map(catalog.venues.map((venue) => [venue.abbr, venue]));
  const cached = createReaderCache(), inflight = createSharedTasks({ concurrency: 6 });
  const vocabulary = createSharedTasks({ maxCached: 1 });
  const searches = createSharedTasks({ maxCached: 4 });
  const scopedBrowsing = createSharedTasks({ maxCached: 2 });
  const legacySearches = createSharedTasks({ maxCached: 1 });
  function engine(papers, preparedIndex) {
    return createSnapshotEngine({ manifest: { ...manifest, paper_count: papers.length }, catalog, papers, preparedIndex });
  }
  async function chunk(entry, context = {}) {
    throwIfAborted(context.signal);
    if (cached.has(entry.path)) return cached.get(entry.path);
    return inflight.run(entry.path, async shared => {
      const { data, size } = await download(entry.path, entry.sha256, "force-cache", undefined, shared.signal, shared.onProgress);
      throwIfAborted(shared.signal);
      if (!Array.isArray(data) || data.length !== entry.count) throw invalid();
      cached.set(entry.path, data, size ?? new TextEncoder().encode(JSON.stringify(data)).byteLength);
      return data;
    }, context);
  }
  async function batches(entries, context = {}) {
    throwIfAborted(context.signal);
    let cursor = 0, loaded = 0;
    const result = new Array(entries.length), batch = new AbortController();
    const abort = () => batch.abort();
    context.signal?.addEventListener("abort", abort, { once: true });
    onProgress({ loaded, total: entries.length });
    try {
      await Promise.all(Array.from({ length: Math.min(descriptor.version >= 5 ? 6 : 4, entries.length) }, async () => {
        while (cursor < entries.length) {
          throwIfAborted(batch.signal);
          const index = cursor++;
          result[index] = await chunk(entries[index], { ...context, signal: batch.signal });
          const progress = { loaded: ++loaded, total: entries.length };
          onProgress(progress); context.onProgress?.(progress);
        }
      }));
      return result.flat();
    } catch (error) { batch.abort(); throw error; }
    finally { context.signal?.removeEventListener("abort", abort); }
  }
  function cards(rows) {
    return rows.map((values) => {
      if (!Array.isArray(values) || values.length !== fields.length) throw invalid();
      const card = Object.fromEntries(fields.map((field, index) => [field, values[index]]));
      const venue = venues.get(card.venue);
      if (!venue) throw invalid();
      return { ...card, level: venue.level, venue_type: venue.type, venue_name: venue.name, abstract: null, abstract_preview: null, authors_preview: card.first_author ? [card.first_author] : [], authors: [], direction_details: [] };
    });
  }
  async function browse(filters, context) {
    const details = descriptor.version >= 2 ? selectedEntries(filters) : null;
    const entries = details ? descriptor.browse.filter(entry => details.some(part => entry.max_id >= part.min_id && entry.min_id <= part.max_id)) : descriptor.browse;
    const key = entries.map(entry => entry.sha256).join();
    return scopedBrowsing.run(key, async shared => engine(cards(await batches(entries, shared))), context);
  }
  async function bucket(value, width = 2) {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
    return [...new Uint8Array(digest).slice(0, 2)].map(byte => byte.toString(16).padStart(2, "0")).join("").slice(0, width);
  }
  async function indexedSearch(params, fuzzy = false, filters = parseParams(params, true), context = {}) {
    if (typeof params.q !== "string" || params.q.length > 2000) queryTokens(params.q);
    const title = normalizedTitle(params.q);
    const titles = await batches(descriptor.search.titles[await bucket(title)] || [], context);
    if (titles.some((row) => !Array.isArray(row) || row.length !== 2 || typeof row[0] !== "string" || !Number.isSafeInteger(row[1]) || row[1] < 1)) throw invalid();
    const exact = titles.filter((row) => row[0] === title).map((row) => row[1]);
    const tokens = params.match === "exact" ? [] : queryTokens(params.q, exact.length > 0);
    let tokenGroups = tokens.map(token => [token]);
    if (fuzzy && descriptor.version >= 3 && tokens.length) {
      const terms = await vocabulary.run("terms", async shared => {
        const rows = await batches(descriptor.search.vocabulary, shared);
        if (rows.some(row => !Array.isArray(row) || row.length !== 2 || !/^[a-z0-9]+$/.test(row[0]) || !Number.isSafeInteger(row[1]) || row[1] < 1)) throw invalid();
        return rows;
      }, context);
      tokenGroups = expandTokens(tokens, terms, 4, title.match(/[a-z0-9]+/g) || []);
    }
    const expanded = [...new Set(tokenGroups.flat())];
    const keys = new Set(await Promise.all(expanded.map(value => bucket(value))));
    const rows = await batches([...keys].flatMap((key) => descriptor.search.terms[key] || []), context);
    const postings = new Map(expanded.map((token) => [token, new Map()])), lengths = new Map();
    for (const row of rows) {
      if (!Array.isArray(row) || row.length !== 4 || typeof row[0] !== "string" || !row.slice(1).every(Number.isSafeInteger) || row[1] < 1 || row[2] < 1 || row[3] < 0) throw invalid();
      if (postings.has(row[0])) { postings.get(row[0]).set(row[1], row[2]); lengths.set(row[1], row[3]); }
    }
    const groups = tokenGroups.map(terms => {
      const ids = new Set();
      for (const term of terms) for (const id of postings.get(term)?.keys() || []) ids.add(id);
      return ids;
    }).sort((left, right) => left.size - right.size);
    const ids = new Set(exact);
    for (const id of groups[0]?.keys() || []) if (groups.every((group) => group.has(id))) ids.add(id);
    // Global postings retain document frequencies for identical BM25 scores.
    // Prune only card downloads using conservative metadata ranges; the shared
    // engine still performs the exact venue/year/direction filters.
    const ranges = selectedEntries(filters).map(entry => [entry.min_id, entry.max_id]).sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const range of ranges) {
      const last = merged.at(-1);
      if (last && range[0] <= last[1] + 1) last[1] = Math.max(last[1], range[1]);
      else merged.push([...range]);
    }
    for (const id of ids) {
      let low = 0, high = merged.length;
      while (low < high) { const middle = (low + high) >>> 1; if (merged[middle][1] < id) low = middle + 1; else high = middle; }
      if (low === merged.length || merged[low][0] > id) ids.delete(id);
    }
    const selected = [...ids].sort((left, right) => left - right);
    const entries = descriptor.browse.filter((entry) => {
      let low = 0, high = selected.length;
      while (low < high) { const middle = (low + high) >>> 1; if (selected[middle] < entry.min_id) low = middle + 1; else high = middle; }
      return low < selected.length && selected[low] <= entry.max_id;
    });
    const papers = cards((await batches(entries, context)).filter((row) => ids.has(row[0])));
    if (papers.length !== ids.size) throw invalid();
    return engine(papers, { postings, lengths, averageLength: descriptor.search.average_length, documentCount: manifest.paper_count, tokenGroups });
  }
  function selectedEntries(filters) {
    return descriptor.details.filter((entry) =>
      (!filters.venue || entry.venues.includes(filters.venue))
      && (!filters.year || entry.years.includes(Number(filters.year)))
      && (!filters.directions.length || filters.directions.some((code) => entry.directions.includes(code)))
      && entry.venues.some((name) => (!filters.level || venues.get(name)?.level === filters.level) && (!filters.type || venues.get(name)?.type === filters.type)));
  }
  const ranked = descriptor.version >= 5 ? createRankedReader({ descriptor, manifest, catalog, batches, cards, chunk, bucket, selectedEntries }) : null;
  return {
    async call(method, params = {}, context = {}) {
      throwIfAborted(context.signal);
      if (ranked && ["papers", "search"].includes(method)) return ranked.call(method, params, context);
      if (method === "papers") {
        const filters = parseParams(params);
        return (await browse(filters, context)).papers(params);
      }
      if (method === "paper") {
        const id = Number(params);
        if (!Number.isSafeInteger(id) || id < 1) throw readerError("论文 ID 不正确");
        const entries = descriptor.details.filter((entry) => entry.min_id <= id && id <= entry.max_id);
        return engine(await batches(entries, context)).paper(id);
      }
      const filters = parseParams(params, true);
      if (descriptor.version >= 2) {
        const mode = params.match || "auto";
        async function runIndexed(fuzzy) {
          const scope = [filters.venue, filters.year, filters.level, filters.type, [...filters.directions].sort()];
          const key = JSON.stringify([params.q, mode === "exact", fuzzy, scope]);
          const prepared = await searches.run(key, shared => indexedSearch(params, fuzzy, filters, shared), context);
          return prepared.search({ ...params, match: mode === "exact" ? "exact" : fuzzy ? "fuzzy" : "keywords" });
        }
        if (mode === "fuzzy") return runIndexed(true);
        const result = await runIndexed(false);
        if (mode !== "auto" || result.total || descriptor.version < 3) return result;
        return runIndexed(true);
      }
      const entries = selectedEntries(filters);
      const key = entries.map((entry) => entry.sha256).join();
      const prepared = await legacySearches.run(key, async shared => engine(await batches(entries, shared)), context);
      return prepared.search(params);
    },
  };
}
