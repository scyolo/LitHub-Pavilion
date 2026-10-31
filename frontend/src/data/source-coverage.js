const HASH = /^[a-f0-9]{64}$/;
const count = value => Number.isSafeInteger(value) && value >= 0;
const fail = () => { throw new Error('覆盖清单未通过校验，请重新导出来源证据。'); };
const http = value => { try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password; } catch { return false; } };
export const COVERAGE_YEARS = [2023, 2024, 2025, 2026];
export const ZERO_YEAR_LABELS = {
  unverified: '待补采核验',
  not_scheduled: '无独立届次',
  joint_edition: '联合或合并届次',
  publication_pending: '出版待核验',
  no_proceedings: '未发布研究论文集',
  edition_unverified: '届次待核验',
  retrieval_failed: '采集待重试',
};
export function zeroYearChecks(source) {
  return Object.fromEntries(COVERAGE_YEARS
    .filter(year => !(source.primary_years[year] || source.associated_years[year]))
    .map(year => [String(year), source.year_checks?.[year] || {
      status: 'unverified', note: '本年度尚无记录，需核对官方出版目录。',
    }]));
}
function validateYearChecks(row, names) {
  if (row.year_checks == null) return;
  if (typeof row.year_checks !== 'object' || Array.isArray(row.year_checks)) fail();
  const zeros = Object.keys(zeroYearChecks(row));
  if (Object.keys(row.year_checks).length !== zeros.length || zeros.some(year => !Object.hasOwn(row.year_checks, year))) fail();
  for (const check of Object.values(row.year_checks)) {
    if (!check || !Object.hasOwn(ZERO_YEAR_LABELS, check.status) || typeof check.note !== 'string' || !check.note.trim() || check.note.length > 1000) fail();
    if (check.status !== 'unverified' || check.evidence_url != null || check.checked_at != null) {
      if (!http(check.evidence_url) || !/^\d{4}-\d{2}-\d{2}$/.test(check.checked_at)) fail();
      const parsed = new Date(check.checked_at + 'T00:00:00Z');
      if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== check.checked_at) fail();
    }
    if (check.canonical_venue != null && (check.status !== 'joint_edition' || check.canonical_venue === row.abbr || !names.has(check.canonical_venue))) fail();
  }
}
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
  for (const row of data.sources) validateYearChecks(row, names);
  if (data.zero_source_year_units != null || data.zero_year_status_counts != null) {
    const expected = {};
    for (const row of data.sources) for (const check of Object.values(zeroYearChecks(row))) expected[check.status] = (expected[check.status] || 0) + 1;
    if (!count(data.zero_source_year_units) || data.zero_source_year_units !== Object.values(expected).reduce((a,b)=>a+b,0) || !data.zero_year_status_counts || typeof data.zero_year_status_counts !== 'object' || Array.isArray(data.zero_year_status_counts)) fail();
    if (Object.keys(expected).length !== Object.keys(data.zero_year_status_counts).length || Object.entries(expected).some(([status,total]) => data.zero_year_status_counts[status] !== total)) fail();
  }
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
export function validateCoverageSnapshot(data, manifest) {
  validateCoverage(data);
  if (data.snapshot_revision !== manifest.revision || data.snapshot_papers !== manifest.paper_count
      || data.snapshot_generated_at !== manifest.generated_at) fail();
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
