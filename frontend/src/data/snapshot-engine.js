import { stemmer } from "stemmer";
import { safeExternalUrl } from "../lib/presentation.js";

export function readerError(message, status = 400, code = "INVALID_PARAM") {
  return Object.assign(new Error(message), { status, code });
}

function parseParams(params = {}, search = false) {
  const values = Object.fromEntries(Object.entries(params).filter(([, value]) => value !== "" && value != null));
  for (const [key, allowed] of Object.entries({ level: ["A", "B"], type: ["conf", "journal"], access: ["oa", "official"], pdf_status: ["pending", "downloaded", "failed", "closed"] })) {
    if (values[key] !== undefined && !allowed.includes(values[key])) throw readerError(`${key} 参数不正确`);
  }
  if (values.year !== undefined && !/^[1-9][0-9]{3}$/.test(String(values.year))) throw readerError("year 必须是四位年份");
  const directions = values.direction === undefined ? [] : [...new Set(String(values.direction).split(",").map((code) => code.trim()))];
  if (directions.some((code) => !code)) throw readerError("direction 必须是非空 code");
  const venue = values.venue === undefined ? null : String(values.venue).trim();
  if (venue === "") throw readerError("venue 必须是非空缩写");
  const page = Number(values.page ?? 1), size = Number(values.size ?? 20);
  if (!Number.isSafeInteger(page) || page < 1 || !Number.isSafeInteger(size) || size < 1 || size > 100) throw readerError("page>=1 且 1<=size<=100");
  const sort = values.sort ?? (search ? "relevance" : "created_desc");
  if (!["created_desc", "year_desc", "citation_desc", ...(search ? ["relevance"] : [])].includes(sort)) throw readerError("不支持的论文排序");
  return { ...values, directions, venue, page, size, sort };
}

function queryTokens(q) {
  if (typeof q !== "string" || q.length > 300) throw readerError("q 最多 300 字符、24 个英文词条");
  const tokens = q.match(/[A-Za-z0-9]+/g) || [];
  if (!tokens.length || /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u{20000}-\u{323af}]/u.test(q)) throw readerError("请输入可检索的英文词条；暂不支持中文检索", 400, "EMPTY_QUERY");
  if (tokens.length > 24) throw readerError("q 最多 300 字符、24 个英文词条");
  return [...new Set(tokens.map((token) => stemmer(token.toLowerCase())))];
}

export function createSnapshotEngine({ manifest, catalog, papers }) {
  if (manifest.schema_version !== 1 || !Number.isFinite(Date.parse(manifest.generated_at)) || !Array.isArray(papers) || papers.length !== manifest.paper_count || !Array.isArray(catalog?.venues) || !Array.isArray(catalog?.directions) || !Array.isArray(catalog?.logs)) throw readerError("静态快照格式不正确，请重新导出", 503, "INVALID_SNAPSHOT");
  const byId = new Map(), venueMap = new Map(catalog.venues.map((venue) => [venue.abbr, venue]));
  for (const paper of papers) {
    if (!Number.isSafeInteger(paper.id) || paper.id <= 0 || byId.has(paper.id) || !venueMap.has(paper.venue) || !["A", "B"].includes(paper.level) || !["conf", "journal"].includes(paper.venue_type) || typeof paper.title !== "string" || !Array.isArray(paper.directions) || !Array.isArray(paper.authors) || !Array.isArray(paper.direction_details)) throw readerError("静态快照含重复或无效论文", 503, "INVALID_SNAPSHOT");
    for (const field of ["official_url", "oa_url"]) if (paper[field] && !safeExternalUrl(paper[field])) throw readerError("静态快照含不安全的论文链接", 503, "INVALID_SNAPSHOT");
    byId.set(paper.id, paper);
  }
  const timestamp = Date.parse(manifest.generated_at), currentYear = new Date(timestamp).getUTCFullYear();
  const timestamps = new Map(papers.map((paper) => [paper.id, Date.parse(paper.created_at) || 0]));
  let index;
  function searchIndex() {
    if (index) return index;
    const postings = new Map(), lengths = new Map();
    let totalLength = 0;
    for (const paper of papers) {
      const terms = `${paper.title} ${paper.abstract || ""}`.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
      lengths.set(paper.id, terms.length);
      totalLength += terms.length;
      const frequency = new Map();
      for (const term of terms) {
        const token = /^[a-z0-9]+$/.test(term) ? stemmer(term) : term;
        frequency.set(token, (frequency.get(token) || 0) + 1);
      }
      for (const [token, count] of frequency) {
        if (!postings.has(token)) postings.set(token, new Map());
        postings.get(token).set(paper.id, count);
      }
    }
    index = { postings, lengths, averageLength: totalLength / Math.max(1, papers.length) || 1 };
    return index;
  }
  function matches(paper, filters) {
    const venue = venueMap.get(paper.venue);
    return (!filters.level || paper.level === filters.level && venue.level === filters.level)
      && (!filters.type || venue.type === filters.type)
      && (!filters.venue || paper.venue === filters.venue)
      && (!filters.year || paper.year === Number(filters.year))
      && (!filters.pdf_status || paper.pdf_status === filters.pdf_status)
      && (!filters.directions.length || filters.directions.some((code) => paper.directions.includes(code)))
      && (!filters.access || (filters.access === "oa" ? Boolean(paper.oa_url) : !paper.oa_url));
  }
  function compare(sort, scores) {
    return (a, b) => {
      let difference;
      if (sort === "relevance") difference = scores.get(a.id) - scores.get(b.id);
      else if (sort === "year_desc") difference = b.year - a.year;
      else if (sort === "citation_desc") difference = (b.citation_count || 0) - (a.citation_count || 0);
      else difference = timestamps.get(b.id) - timestamps.get(a.id);
      return difference || b.id - a.id;
    };
  }
  function listing(params, isSearch) {
    const filters = parseParams(params, isSearch);
    let candidates = papers;
    const scores = new Map();
    if (isSearch) {
      const tokens = queryTokens(params.q);
      const { postings, lengths, averageLength } = searchIndex();
      const groups = tokens.map((token) => postings.get(token) || new Map()).sort((a, b) => a.size - b.size);
      candidates = [];
      for (const id of groups[0].keys()) {
        if (!groups.every((group) => group.has(id))) continue;
        let score = 0;
        for (const group of groups) {
          const frequency = group.get(id);
          const idf = Math.max(1e-6, Math.log((papers.length - group.size + 0.5) / (group.size + 0.5)));
          score -= idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * lengths.get(id) / averageLength));
        }
        scores.set(id, score);
        candidates.push(byId.get(id));
      }
    }
    const rows = candidates.filter((paper) => matches(paper, filters)).sort(compare(filters.sort, scores));
    return { total: rows.length, page: filters.page, size: filters.size, items: rows.slice((filters.page - 1) * filters.size, filters.page * filters.size).map((paper) => isSearch ? { ...paper, score: Number(scores.get(paper.id).toFixed(4)) } : paper) };
  }
  function dashboard(params = {}) {
    const filters = parseParams(params);
    const rows = papers.filter((paper) => matches(paper, filters));
    const by_level = { A: 0, B: 0 }, by_type = { conf: 0, journal: 0 };
    const annual = Array.from({ length: Math.max(0, currentYear - 2023 + 1) }, (_, i) => ({ year: i + 2023, A: 0, B: 0, total: 0 }));
    const directionCounts = new Map(), venueCounts = new Map(), venueYears = new Map();
    let with_oa_link = 0, with_abstract = 0, confirmed_count = 0, recent_count = 0;
    for (const paper of rows) {
      by_level[paper.level]++; by_type[paper.venue_type]++;
      with_oa_link += Number(Boolean(paper.oa_url));
      with_abstract += Number(Boolean(paper.abstract));
      confirmed_count += Number(Boolean(paper.venue_confirmed));
      const created = timestamps.get(paper.id);
      recent_count += Number(created >= timestamp - 7 * 86400000 && created <= timestamp);
      const year = annual[paper.year - 2023];
      if (year) { year[paper.level]++; year.total++; }
      for (const code of new Set(paper.directions)) directionCounts.set(code, (directionCounts.get(code) || 0) + 1);
      venueCounts.set(paper.venue, (venueCounts.get(paper.venue) || 0) + 1);
      if (!venueYears.has(paper.venue)) venueYears.set(paper.venue, new Map());
      const years = venueYears.get(paper.venue);
      years.set(paper.year, (years.get(paper.year) || 0) + 1);
    }
    const configured = catalog.venues.filter((venue) => (!filters.level || venue.level === filters.level) && (!filters.type || venue.type === filters.type));
    return {
      generated_at: manifest.generated_at, total: rows.length, with_oa_link, with_abstract, confirmed_count, recent_count, by_level, by_type, annual,
      directions: catalog.directions.map((direction) => ({ ...direction, paper_count: directionCounts.get(direction.code) || 0 })).filter((direction) => direction.enabled || direction.paper_count),
      configured_venues: configured.length, venues_with_papers: venueCounts.size, last_crawl: catalog.last_crawl,
      venues: configured.filter((venue) => !filters.venue || venue.abbr === filters.venue).map((venue) => ({ ...venue, paper_count: venueCounts.get(venue.abbr) || 0,
        years: [...(venueYears.get(venue.abbr) || new Map())].sort(([a], [b]) => a - b).map(([year, count]) => ({ year, count })) })),
    };
  }
  return {
    papers: (params = {}) => listing(params, false),
    search: (params = {}) => listing(params, true),
    paper: (id) => {
      const paper = /^\d+$/.test(String(id)) ? byId.get(Number(id)) : null;
      if (!paper) throw readerError("论文不存在", 404, "PAPER_NOT_FOUND");
      return { ...paper, venue: { abbr: paper.venue, name: paper.venue_name, type: paper.venue_type, level: paper.level }, directions: paper.direction_details, mode: "snapshot" };
    },
    dashboard,
    directions: () => ({ items: dashboard().directions.filter((direction) => direction.enabled) }),
    venues: (params = {}) => ({ items: dashboard(params).venues }),
    stats: () => { const result = dashboard(); return { ...result, by_direction: Object.fromEntries(result.directions.map((d) => [d.code, d.paper_count])), by_year: Object.fromEntries(result.annual.map((year) => [year.year, year.total])), pdf_archived: 0, last_crawl_at: catalog.last_crawl?.started_at }; },
    crawlLogs: (page = 1) => { const params = parseParams({ page, size: 10 }); return { total: catalog.logs.length, page: params.page, size: 10, items: catalog.logs.slice((page - 1) * 10, page * 10) }; },
    crawlStatus: () => ({ running: false, read_only: true, schedule: null, mode: "snapshot", generated_at: manifest.generated_at, revision: manifest.revision }),
    trigger: () => { throw readerError("静态网站为只读，请在本地 Docker 中管理采集", 405, "READ_ONLY"); },
  };
}
