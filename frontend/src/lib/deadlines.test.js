import { describe, expect, it } from "vitest";
import { calendarCells, dateKey, deadlineStatus, filterDeadlines, toICS, validateFeed } from "./deadlines.js";

const event = {
  id: "www-2027-r1", venue: "WWW", venue_name: "The Web Conference", year: 2027,
  level: "A", area: "交叉/综合/新兴", round: "round 1", deadline_utc: "2026-10-01T20:00:00Z",
  abstract_deadline_utc: "2026-09-30T20:00:00Z", timezone: "AoE", link: "https://www2027.thewebconf.org/",
  source_url: "https://github.com/ccfddl/ccf-deadlines/blob/main/conference/MX/www.yml",
};
const now = Date.parse("2026-10-01T00:00:00Z");

describe("deadline calendar semantics", () => {
  it("distinguishes expired, upcoming and unannounced times", () => {
    expect(deadlineStatus(event, now)).toBe("upcoming");
    expect(deadlineStatus(event, Date.parse(event.deadline_utc))).toBe("past");
    expect(deadlineStatus({ ...event, deadline_utc: null }, now)).toBe("tba");
    expect(deadlineStatus({ ...event, deadline_utc: "broken" }, now)).toBe("tba");
  });
  it("uses the selected timezone for the calendar date, including month boundaries", () => {
    expect(dateKey(event.deadline_utc, "Asia/Shanghai")).toBe("2026-10-02");
    expect(dateKey(event.deadline_utc, "UTC")).toBe("2026-10-01");
    expect(dateKey("2026-09-30T20:00:00Z", "Asia/Shanghai")).toBe("2026-10-01");
  });
  it("builds a complete Monday-first six-week grid", () => {
    const cells = calendarCells("2026-10");
    expect(cells).toHaveLength(42);
    expect(cells[0].key).toBe("2026-09-28");
    expect(cells.filter(c => c.inMonth)).toHaveLength(31);
  });
  it("combines level, area, status and keyword filters", () => {
    const data = [event, { ...event, id: "b", level: "B" }];
    expect(filterDeadlines(data, { level: "B", q: "web", status: "upcoming" }, now).map(e => e.id)).toEqual(["b"]);
    expect(filterDeadlines(data, { area: "人工智能" }, now)).toEqual([]);
  });
  it("exports real UTC times, stable ids and escaped text without unknown deadlines", () => {
    const ics = toICS([{ ...event, venue_name: "Conference, research;\nnotes" }, { ...event, id: "tbd", deadline_utc: null }], now);
    expect(ics).toContain("DTSTART:20261001T200000Z\r\n");
    expect(ics.match(/BEGIN:VEVENT/g)).toHaveLength(1);
    expect(ics).toContain("UID:www-2027-r1@lithub-pavilion");
    expect(ics).not.toContain("DTSTART:null");
    expect(ics).toContain("\\,");
    expect(ics).toContain("\\;");
    expect(ics.split("\r\n").every(line => new TextEncoder().encode(line).length <= 75)).toBe(true);
  });
  it("rejects incomplete feeds, duplicate identities and invalid UTC dates", () => {
    expect(() => validateFeed({})).toThrow();
    const feed = { version: 1, generated_at: "2026-10-01T00:00:00Z", source: { name: "CCFDDL", url: "https://github.com/ccfddl/ccf-deadlines" }, coverage: { configured_conferences: 190, matched_conferences: 1, missing_venues: [] }, events: [event] };
    expect(validateFeed(feed).events).toHaveLength(1);
    expect(() => validateFeed({ ...feed, events: [event, event] })).toThrow();
    expect(() => validateFeed({ ...feed, events: [{ ...event, deadline_utc: "2026-02-30T00:00:00Z" }] })).toThrow();
    expect(() => validateFeed({ ...feed, events: [{ ...event, link: "javascript:alert(1)" }] })).toThrow();
  });
});
