const HASH = /^[a-f0-9]{64}$/;
const count = value => Number.isSafeInteger(value) && value >= 0;
const fail = () => { throw new Error('覆盖清单未通过校验，请重新导出来源证据。'); };
const http = value => { try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password; } catch { return false; } };
function descriptor(entry) { return entry && HASH.test(entry.sha256) && entry.path === 'coverage/associations-' + entry.sha256 + '.json' && count(entry.count) && entry.count > 0; }
function years(value) { return value && typeof value === 'object' && Object.entries(value).every(([y,n]) => /^202[3-6]$/.test(y) && count(n)); }
export function validateCoverage(data) {
  if (data?.version !== 1 || !HASH.test(data.snapshot_revision) || !Array.isArray(data.sources) || data.sources.length > 1000 || !count(data.snapshot_papers) || data.configured_sources !== data.sources.length || data.full_coverage_verified !== false || !Number.isFinite(Date.parse(data.generated_at)) || !Number.isFinite(Date.parse(data.snapshot_generated_at))) fail();
  const names = new Set();
  for (const row of data.sources) {
    if (!row || typeof row.abbr !== 'string' || !row.abbr || names.has(row.abbr) || typeof row.name !== 'string' || !['A','B'].includes(row.level) || !['conf','journal'].includes(row.type) || !count(row.primary_count) || !count(row.associated_count) || !years(row.primary_years) || !years(row.associated_years) || !['indexed','journal_linked','unresolved'].includes(row.status)) fail();
    if (Object.values(row.primary_years).reduce((a,b)=>a+b,0) !== row.primary_count || (row.associated_count > 0 ? !descriptor(row.associations) : row.associations != null)) fail();
    if (row.status !== (row.primary_count ? 'indexed' : row.associated_count ? 'journal_linked' : 'unresolved')) fail();
    if (row.note != null && (typeof row.note !== "string" || row.note.length > 1000)) fail();
    if (row.evidence_url != null && !http(row.evidence_url)) fail();
    names.add(row.abbr);
  }
  if (data.direct_sources !== data.sources.filter(s=>s.primary_count>0).length || data.represented_sources !== data.sources.filter(s=>s.primary_count+s.associated_count>0).length) fail();
  return data;
}
export function validateAssociations(data,source,revision) {
  if (data?.version !== 1 || data.venue !== source.abbr || data.snapshot_revision !== revision || !Array.isArray(data.papers) || data.papers.length !== source.associations.count) fail();
  const seen = new Set();
  for (const p of data.papers) {
    const key = p.id + ':' + p.event_year;
    if (!count(p.id) || !p.id || typeof p.title !== 'string' || !p.title || typeof p.canonical_venue !== 'string' || !Number.isInteger(p.event_year) || p.event_year<2023 || p.event_year>2026 || !Number.isInteger(p.publication_year) || !http(p.official_url) || !http(p.evidence_url) || seen.has(key)) fail();
    seen.add(key);
  }
  if (new Set(data.papers.map(p=>p.id)).size !== source.associated_count) fail();
  return data;
}
async function read(path,signal,fetcher) {
  const response=await fetcher(import.meta.env.BASE_URL+'data-sources/'+path,{signal,credentials:'omit',redirect:'error',cache:'no-cache'});
  if (!response.ok) throw new Error('来源覆盖清单暂不可用，请稍后重试。');
  const content=await response.arrayBuffer(); if(content.byteLength>4*1024*1024) fail();return content;
}
export async function loadCoverage(signal,fetcher=fetch) {return validateCoverage(JSON.parse(new TextDecoder().decode(await read('source-coverage.json',signal,fetcher))));}
export async function loadAssociations(source,revision,signal,fetcher=fetch) {
  if(!descriptor(source.associations)) fail();
  const bytes=await read(source.associations.path,signal,fetcher);
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(n=>n.toString(16).padStart(2,'0')).join('');
  if(digest!==source.associations.sha256) fail();
  return validateAssociations(JSON.parse(new TextDecoder().decode(bytes)),source,revision);
}
