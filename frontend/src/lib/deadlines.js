import { safeExternalUrl } from "./presentation.js";

const DAY = 86400000;
const validUTC = value => typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value)
  && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().replace(".000Z", "Z") === value;

export function validateFeed(feed) {
  const fail = () => { throw new Error("截稿数据格式不正确，请重新同步日历数据。"); };
  if (feed?.version !== 1 || !validUTC(feed.generated_at) || !Array.isArray(feed.events) || feed.events.length > 10000
    || typeof feed.source?.name !== "string" || !safeExternalUrl(feed.source?.url)
    || !Number.isSafeInteger(feed.coverage?.configured_conferences) || !Number.isSafeInteger(feed.coverage?.matched_conferences)
    || feed.coverage.matched_conferences < 0 || feed.coverage.matched_conferences > feed.coverage.configured_conferences
    || !Array.isArray(feed.coverage.missing_venues) || !feed.coverage.missing_venues.every(v => typeof v === "string")) fail();
  const ids = new Set();
  for (const event of feed.events) {
    if (!event || typeof event.id !== "string" || !/^[\w-]{1,100}$/.test(event.id) || ids.has(event.id)
      || !["A", "B"].includes(event.level) || !Number.isInteger(event.year) || event.year < 2000 || event.year > 2100
      || ["venue", "venue_name", "area", "round"].some(key => typeof event[key] !== "string")
      || ["deadline_utc", "abstract_deadline_utc"].some(key => event[key] != null && !validUTC(event[key]))
      || ["link", "source_url"].some(key => event[key] != null && !safeExternalUrl(event[key]))) fail();
    ids.add(event.id);
  }
  return feed;
}

export async function loadDeadlineFeed(signal) {
  const response = await fetch(`${import.meta.env.BASE_URL}deadlines.json`, { signal, cache: "no-cache", mode: "same-origin", credentials: "omit", redirect: "error" });
  if (!response.ok) throw new Error("暂时无法读取截稿日历。论文浏览不受影响，请稍后重试。");
  const text = await response.text();
  if (text.length > 4 * 1024 * 1024) throw new Error("截稿数据超过大小限制。");
  return validateFeed(JSON.parse(text));
}

export function deadlineStatus(event, now = Date.now()) {
  const stamp = Date.parse(event.deadline_utc);
  return !Number.isFinite(stamp) ? "tba" : stamp <= now ? "past" : "upcoming";
}

export function dateKey(value, timeZone = "Asia/Shanghai") {
  if (value == null || !Number.isFinite(new Date(value).getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date(value));
  return ["year", "month", "day"].map(type => parts.find(p => p.type === type).value).join("-");
}

export function formatDeadline(value, timeZone = "Asia/Shanghai", compact = false) {
  if (!value || !Number.isFinite(Date.parse(value))) return "待公布";
  return new Intl.DateTimeFormat("zh-CN", { timeZone, year: compact ? undefined : "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(value));
}

export function countdown(event, now = Date.now()) {
  const status = deadlineStatus(event, now);
  if (status !== "upcoming") return status === "past" ? "已截止" : "待公布";
  const remaining = Date.parse(event.deadline_utc) - now;
  if (remaining >= DAY) return `${Math.floor(remaining / DAY)} 天 ${Math.floor(remaining % DAY / 3600000)} 小时`;
  if (remaining >= 3600000) return `${Math.floor(remaining / 3600000)} 小时 ${Math.floor(remaining % 3600000 / 60000)} 分`;
  return remaining >= 60000 ? `${Math.floor(remaining / 60000)} 分钟` : "不足 1 分钟";
}

export function filterDeadlines(events, filters = {}, now = Date.now()) {
  const query = (filters.q || "").trim().toLowerCase();
  return events.filter(e => (!filters.level || e.level === filters.level) && (!filters.area || e.area === filters.area)
    && (!filters.status || filters.status === "all" || deadlineStatus(e, now) === filters.status)
    && (!query || `${e.venue} ${e.venue_name} ${e.area} ${e.round} ${e.place || ""}`.toLowerCase().includes(query)))
    .sort((a, b) => (Date.parse(a.deadline_utc) || Infinity) - (Date.parse(b.deadline_utc) || Infinity) || a.venue.localeCompare(b.venue) || a.id.localeCompare(b.id));
}

export function calendarCells(month) {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) throw new Error("无效月份");
  const [year, value] = month.split("-").map(Number);
  const first = new Date(Date.UTC(year, value - 1, 1));
  const start = first.getTime() - (first.getUTCDay() + 6) % 7 * DAY;
  return Array.from({ length: 42 }, (_, i) => {
    const date = new Date(start + i * DAY);
    return { key: date.toISOString().slice(0, 10), day: date.getUTCDate(), inMonth: date.getUTCMonth() === value - 1 };
  });
}

export function adjacentMonth(month, delta) {
  const [year, value] = month.split("-").map(Number);
  return new Date(Date.UTC(year, value - 1 + delta, 1)).toISOString().slice(0, 7);
}

const escapeICS = value => String(value || "").replace(/\\/g, "\\\\").replace(/\r?\n|\r/g, "\\n").replace(/;/g, "\\;").replace(/,/g, "\\,");
const utcICS = value => new Date(value).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
function foldLine(line) {
  let output = "", current = "", bytes = 0;
  for (const character of line) {
    const size = new TextEncoder().encode(character).length;
    if (bytes + size > 75) { output += `${current}\r\n`; current = " "; bytes = 1; }
    current += character; bytes += size;
  }
  return output + current;
}

export function toICS(events, now = Date.now()) {
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//LitHub Pavilion//CCF Deadlines//ZH", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:CCF 截稿日历"];
  for (const event of events.filter(e => validUTC(e.deadline_utc))) {
    const description = [event.venue_name, `CCF ${event.level} · ${event.round}`, event.abstract_deadline_utc ? `摘要截止（UTC）：${event.abstract_deadline_utc}` : "摘要截止：未提供，请确认官网", "社区汇总，请以会议官网为准。", event.source_url].filter(Boolean).join("\n");
    lines.push("BEGIN:VEVENT", `UID:${event.id}@lithub-pavilion`, `DTSTAMP:${utcICS(now)}`, `DTSTART:${utcICS(event.deadline_utc)}`, "DURATION:PT1M", `SUMMARY:${escapeICS(`${event.venue} ${event.year} · 全文截稿 · ${event.round}`)}`, `DESCRIPTION:${escapeICS(description)}`);
    if (safeExternalUrl(event.link)) lines.push(`URL:${event.link}`);
    lines.push("END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  return lines.map(foldLine).join("\r\n") + "\r\n";
}
