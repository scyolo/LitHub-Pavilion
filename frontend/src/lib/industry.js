import { matchesText } from "./search.js";
import { safeExternalUrl } from "./presentation.js";

export const REPORT_KINDS = {
  tech_report: "技术报告",
  system_card: "系统卡",
  model_card: "模型卡",
  paper: "研究论文",
  journal_article: "期刊论文",
  blog: "官方博客",
  code_release: "代码与权重",
};

const KINDS = new Set(Object.keys(REPORT_KINDS));
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const ARXIV_ID = /^\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}$/;
const ORG_CODE = /^[a-z0-9][a-z0-9-]{1,19}$/;
const REPORT_ID = /^[a-z0-9][a-z0-9-]{1,80}$/;

function validDate(value) {
  if (typeof value !== "string" || !DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function validateIndustryFeed(feed) {
  const fail = () => { throw new Error("大厂技术报告数据格式不正确，请重新生成目录。"); };
  if (feed?.schema_version !== 1 || typeof feed.title !== "string" || !UTC.test(feed.generated_at || "")
    || typeof feed.source_note !== "string" || !Array.isArray(feed.orgs) || !Array.isArray(feed.reports)
    || feed.orgs.length < 1 || feed.orgs.length > 200 || feed.reports.length < 1 || feed.reports.length > 2000) fail();
  const orgs = new Map();
  for (const org of feed.orgs) {
    if (!org || typeof org.code !== "string" || !ORG_CODE.test(org.code) || orgs.has(org.code)
      || ["name", "name_en", "country", "note"].some(key => typeof org[key] !== "string" || !org[key].trim())
      || !Number.isSafeInteger(org.count) || org.count < 1) fail();
    orgs.set(org.code, org);
  }
  const ids = new Set();
  const counts = new Map();
  for (const report of feed.reports) {
    if (!report || typeof report.id !== "string" || !REPORT_ID.test(report.id) || ids.has(report.id)
      || !orgs.has(report.org) || typeof report.title !== "string" || !report.title.trim()
      || !KINDS.has(report.kind) || !Number.isInteger(report.year) || report.year < 2000 || report.year > 2100
      || !validDate(report.published) || Number(report.published.slice(0, 4)) !== report.year
      || !safeExternalUrl(report.url) || !report.url.startsWith("https://")
      || (report.arxiv_id != null && (typeof report.arxiv_id !== "string" || !ARXIV_ID.test(report.arxiv_id)))
      || typeof report.summary !== "string" || !report.summary.trim()
      || !Array.isArray(report.tags) || report.tags.length < 1 || report.tags.length > 6
      || report.tags.some(tag => typeof tag !== "string" || !tag.trim())) fail();
    ids.add(report.id);
    counts.set(report.org, (counts.get(report.org) || 0) + 1);
  }
  for (const org of feed.orgs) if (counts.get(org.code) !== org.count) fail();
  if (!feed.stats || feed.stats.reports !== feed.reports.length || feed.stats.orgs !== feed.orgs.length) fail();
  return feed;
}

export async function loadIndustryFeed(signal) {
  const response = await fetch(`${import.meta.env.BASE_URL}industry.json`, {
    signal, cache: "no-cache", mode: "same-origin", credentials: "omit", redirect: "error",
  });
  if (!response.ok) throw new Error("暂时无法读取大厂技术报告目录。论文浏览不受影响，请稍后重试。");
  const text = await response.text();
  if (text.length > 2 * 1024 * 1024) throw new Error("大厂技术报告数据超过大小限制。");
  try {
    return validateIndustryFeed(JSON.parse(text));
  } catch (error) {
    if (error instanceof SyntaxError) throw new Error("大厂技术报告数据格式不正确，请重新生成目录。");
    throw error;
  }
}

export function kindLabel(kind) {
  return REPORT_KINDS[kind] || kind;
}

export function filterReports(reports, orgs, filters = {}) {
  const orgMap = new Map(orgs.map(org => [org.code, org]));
  return reports.filter(report => {
    const org = orgMap.get(report.org);
    return (!filters.org || report.org === filters.org)
      && (!filters.kind || report.kind === filters.kind)
      && matchesText(filters.q, [report.title, report.summary, report.tags.join(" "), report.year, org?.name, org?.name_en, org?.code]);
  }).sort((a, b) => b.published.localeCompare(a.published) || a.id.localeCompare(b.id));
}

export function groupReports(reports, orgs) {
  const order = new Map(orgs.map((org, index) => [org.code, index]));
  const groups = new Map(orgs.map(org => [org.code, { org, reports: [] }]));
  for (const report of reports) groups.get(report.org)?.reports.push(report);
  return [...groups.values()].filter(group => group.reports.length)
    .sort((a, b) => b.reports.length - a.reports.length || order.get(a.org.code) - order.get(b.org.code));
}
