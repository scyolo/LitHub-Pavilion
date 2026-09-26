import { publicationSortKey, safeExternalUrl } from "../lib/presentation.js";
import { readerError } from "./snapshot-engine.js";

const invalid = () => readerError("静态快照首页摘要校验失败，请重新导出", 503, "INVALID_SNAPSHOT");
const count = (value) => Number.isSafeInteger(value) && value >= 0;
const flag = (value) => value === 0 || value === 1 || typeof value === "boolean";
const venueKeys = ["id", "abbr", "name", "type", "level", "ccf_area", "active"];
const directionKeys = ["code", "name", "enabled"];
const logKeys = ["run_id", "task_type", "status", "papers_new", "papers_updated", "started_at", "finished_at"];
const cardKeys = ["id", "title", "venue", "venue_name", "venue_type", "level", "year", "abstract_preview", "authors_preview", "publication_date", "created_at", "venue_confirmed", "directions", "first_author", "authors_count", "citation_count", "pdf_status", "pdf_source", "doi", "official_url", "oa_url"];
const dashboardKeys = ["total", "with_oa_link", "with_abstract", "confirmed_count", "recent_count", "by_level", "by_type", "annual", "directions", "configured_venues", "venues_with_papers", "venues"];
function keys(value, expected) {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).length !== expected.length || expected.some((key) => !Object.hasOwn(value, key))) throw invalid();
}
function check(condition) { if (!condition) throw invalid(); }
function unique(values) { return new Set(values).size === values.length; }

export function createOverview({ manifest, catalog }) {
  keys(catalog, ["venues", "directions", "logs", "last_crawl", ...(Object.hasOwn(catalog, "overview") ? ["overview"] : [])]);
  check(Array.isArray(catalog.venues) && Array.isArray(catalog.directions) && Array.isArray(catalog.logs));
  const venues = new Map(), directions = new Map();
  for (const venue of catalog.venues) {
    keys(venue, venueKeys);
    check(count(venue.id) && venue.id > 0 && typeof venue.abbr === "string" && typeof venue.name === "string" && !venues.has(venue.abbr) && ["A", "B"].includes(venue.level) && ["conf", "journal"].includes(venue.type) && flag(venue.active));
    venues.set(venue.abbr, venue);
  }
  for (const direction of catalog.directions) {
    keys(direction, directionKeys);
    check(typeof direction.code === "string" && typeof direction.name === "string" && !directions.has(direction.code) && flag(direction.enabled));
    directions.set(direction.code, direction);
  }
  check(catalog.logs.length <= 100);
  for (const log of catalog.logs) keys(log, logKeys);
  if (catalog.last_crawl !== null) keys(catalog.last_crawl, [...logKeys.filter((key) => key !== "task_type"), "failed_units"]);
  if (!Object.hasOwn(catalog, "overview")) return null;
  keys(catalog.overview, ["version", "scopes"]);
  check(catalog.overview.version === 1 && Array.isArray(catalog.overview.scopes) && catalog.overview.scopes.length === 9);
  const scopes = new Map();
  for (const scope of catalog.overview.scopes) {
    keys(scope, ["level", "type", "dashboard", "latest"]);
    check([null, "A", "B"].includes(scope.level) && [null, "conf", "journal"].includes(scope.type));
    const key = `${scope.level || ""}:${scope.type || ""}`;
    check(!scopes.has(key)); scopes.set(key, scope);
    const data = scope.dashboard;
    keys(data, dashboardKeys);
    for (const name of ["total", "with_oa_link", "with_abstract", "confirmed_count", "recent_count", "configured_venues", "venues_with_papers"]) check(count(data[name]));
    for (const name of ["with_oa_link", "with_abstract", "confirmed_count", "recent_count"]) check(data[name] <= data.total);
    check(data.total <= manifest.paper_count && data.venues_with_papers <= data.configured_venues);
    keys(data.by_level, ["A", "B"]); keys(data.by_type, ["conf", "journal"]);
    check(Object.values(data.by_level).every(count) && data.by_level.A + data.by_level.B === data.total);
    check(Object.values(data.by_type).every(count) && data.by_type.conf + data.by_type.journal === data.total);
    if (scope.level) check(data.by_level[scope.level] === data.total);
    if (scope.type) check(data.by_type[scope.type] === data.total);
    check(Array.isArray(data.annual) && data.annual.length === Math.max(0, new Date(manifest.generated_at).getUTCFullYear() - 2022));
    for (const [index, year] of data.annual.entries()) {
      keys(year, ["year", "A", "B", "total"]);
      check(year.year === 2023 + index && [year.A, year.B, year.total].every(count) && year.A + year.B === year.total && year.total <= data.total);
    }
    check(data.annual.reduce((sum, year) => sum + year.total, 0) <= data.total);
    check(Array.isArray(data.directions) && unique(data.directions.map((d) => d.code)));
    for (const direction of data.directions) {
      keys(direction, [...directionKeys, "paper_count"]);
      const known = directions.get(direction.code);
      check(known && direction.name === known.name && direction.enabled === known.enabled && count(direction.paper_count) && direction.paper_count <= data.total);
    }
    check(catalog.directions.filter((d) => d.enabled).every((d) => data.directions.some((value) => value.code === d.code)));
    const configured = catalog.venues.filter((v) => (!scope.level || v.level === scope.level) && (!scope.type || v.type === scope.type));
    check(Array.isArray(data.venues) && data.configured_venues === configured.length && data.venues.length === configured.length && unique(data.venues.map((v) => v.abbr)));
    for (const venue of data.venues) {
      keys(venue, [...venueKeys, "paper_count", "years"]);
      const known = configured.find((v) => v.abbr === venue.abbr);
      check(known && venueKeys.every((key) => venue[key] === known[key]) && count(venue.paper_count) && Array.isArray(venue.years));
      check(unique(venue.years.map((y) => y.year)));
      for (const year of venue.years) { keys(year, ["year", "count"]); check(count(year.year) && count(year.count)); }
      check(venue.years.reduce((sum, year) => sum + year.count, 0) === venue.paper_count);
    }
    check(data.venues.reduce((sum, v) => sum + v.paper_count, 0) === data.total && data.venues.filter((v) => v.paper_count).length === data.venues_with_papers);
    check(Array.isArray(scope.latest) && scope.latest.length === Math.min(5, data.total) && unique(scope.latest.map((p) => p.id)));
    for (const [index, paper] of scope.latest.entries()) {
      keys(paper, cardKeys);
      const venue = venues.get(paper.venue);
      check(count(paper.id) && paper.id > 0 && typeof paper.title === "string" && paper.title.trim() && venue && venue.name === paper.venue_name && venue.type === paper.venue_type && ["A", "B"].includes(paper.level));
      check((!scope.level || paper.level === scope.level && venue.level === scope.level) && (!scope.type || paper.venue_type === scope.type));
      check(Number.isInteger(paper.year) && paper.year >= 2000 && paper.year <= 2100 && count(paper.authors_count) && count(paper.citation_count));
      check(paper.abstract_preview === null || typeof paper.abstract_preview === "string");
      check(Array.isArray(paper.authors_preview) && paper.authors_preview.every((name) => typeof name === "string") && paper.authors_preview.length <= 3);
      check(Array.isArray(paper.directions) && unique(paper.directions) && paper.directions.every((code) => directions.has(code)));
      for (const name of ["official_url", "oa_url"]) check(paper[name] === null || typeof paper[name] === "string" && Boolean(safeExternalUrl(paper[name])));
      if (index) {
        const previous = scope.latest[index - 1];
        const a = publicationSortKey(previous), b = publicationSortKey(paper);
        check(a > b || a === b && previous.id > paper.id);
      }
    }
  }
  check(scopes.get(":")?.dashboard.total === manifest.paper_count);
  function select(params = {}) {
    const values = Object.entries(params).filter(([, value]) => value !== "" && value != null);
    if (values.some(([key]) => !["level", "type"].includes(key))) return null;
    return scopes.get(`${params.level || ""}:${params.type || ""}`) || null;
  }
  function dashboard(scope) { return { ...scope.dashboard, generated_at: manifest.generated_at, last_crawl: catalog.last_crawl }; }
  return {
    supports: (method, params) => ["directions", "stats", "crawlLogs", "crawlStatus"].includes(method) || ["dashboard", "latest", "venues"].includes(method) && Boolean(select(params)),
    dashboard: (params) => dashboard(select(params)),
    latest: (params) => { const scope = select(params); return { total: scope.dashboard.total, page: 1, size: 5, items: scope.latest }; },
    directions: () => ({ items: scopes.get(":").dashboard.directions.filter((d) => d.enabled) }),
    venues: (params) => ({ items: select(params).dashboard.venues }),
    stats: () => { const result = dashboard(scopes.get(":")); return { ...result, by_direction: Object.fromEntries(result.directions.map((d) => [d.code, d.paper_count])), by_year: Object.fromEntries(result.annual.map((y) => [y.year, y.total])), pdf_archived: 0, last_crawl_at: catalog.last_crawl?.started_at }; },
    crawlStatus: () => ({ running: false, read_only: true, schedule: null, mode: "snapshot", generated_at: manifest.generated_at, revision: manifest.revision }),
    crawlLogs: (page = 1) => { if (!Number.isSafeInteger(Number(page)) || page < 1) throw readerError("page 必须大于零"); return { total: catalog.logs.length, page: Number(page), size: 10, items: catalog.logs.slice((page - 1) * 10, page * 10) }; },
  };
}
