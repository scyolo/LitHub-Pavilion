import { safeExternalUrl } from '../lib/presentation.js';
import { readerError } from './reader-errors.js';

const normalized = value => String(value || '').normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
const keys = ['reference_id', 'title', 'authors', 'venue', 'year', 'level', 'status', 'official_url', 'preprint_url', 'aliases', 'directions', 'evidence_sha256', 'verified_on'].sort();
const invalid = () => readerError('录用记录校验失败，请重新导出', 503, 'INVALID_SNAPSHOT');

export function validateAcceptedReferences(rows, venues) {
  if (!Array.isArray(rows) || rows.length > 200) throw invalid();
  const known = new Map(venues.map(v => [v.abbr, v])), seen = new Set();
  for (const row of rows) {
    if (!row || Object.keys(row).sort().join() !== keys.join()) throw invalid();
    const venue = known.get(row.venue);
    if (!venue || venue.type !== 'conf' || venue.level !== row.level || !['A', 'B'].includes(row.level)
        || row.status !== 'accepted_publication_unverified' || !/^[a-z0-9-]{8,80}$/.test(row.reference_id) || seen.has(row.reference_id)
        || !Number.isSafeInteger(row.year) || row.year < 2023 || row.year > 2100 || typeof row.title !== 'string' || !row.title.trim() || row.title.length > 2000
        || !Array.isArray(row.authors) || !row.authors.length || row.authors.some(a => typeof a !== 'string' || !a || a.length > 200)
        || !Array.isArray(row.aliases) || row.aliases.some(a => typeof a !== 'string' || !a || a.length > 2000)
        || !Array.isArray(row.directions) || row.directions.some(d => typeof d !== 'string' || !/^[a-z]+$/.test(d))
        || !safeExternalUrl(row.official_url) || !/^[a-f0-9]{64}$/.test(row.evidence_sha256) || !/^20\d{2}-\d{2}-\d{2}$/.test(row.verified_on)
        || row.preprint_url !== null && !/^https:\/\/arxiv\.org\/abs\/\d{4}\.\d{4,5}$/.test(row.preprint_url)) throw invalid();
    seen.add(row.reference_id);
  }
}

export function attachAcceptedReferences(catalog, result, q, params = {}) {
  const query = normalized(q), topic = result.query_topic?.code;
  if (!query && !topic && (String(q || '').trim() || !params.venue)) return result;
  const directions = String(params.direction || '').split(',').filter(Boolean);
  const rows = (catalog.accepted_papers || []).filter(row => {
    if (params.pdf_status || params.level && params.level !== row.level || params.type && params.type !== 'conf'
        || params.venue && params.venue !== row.venue || params.year && Number(params.year) !== row.year
        || directions.length && !directions.some(d => row.directions.includes(d)) || topic && !row.directions.includes(topic)
        || params.access && Boolean(row.preprint_url) !== (params.access === 'oa')) return false;
    const values = [normalized(row.title), ...row.aliases.map(normalized)];
    return topic || !query || (params.match === 'exact' ? query === values[0] : query.split(' ').every(word => values.join(' ').includes(word)));
  });
  return rows.length ? {...result, accepted_items: rows} : result;
}

export function acceptedTitleParams(catalog, params) {
  if ((params.match || 'auto') !== 'auto' || !normalized(params.q)) return params;
  const exact = {...params, match: 'exact'};
  return attachAcceptedReferences(catalog, {total: 0, items: []}, params.q, exact).accepted_items?.length ? exact : params;
}
