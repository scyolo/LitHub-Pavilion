import { describe, expect, it } from "vitest";

import { generated_at, snapshotFixture as fixture } from "../test/snapshot-fixture.js";

async function engine() {
  const { createSnapshotEngine } = await import("./snapshot-engine.js");
  return createSnapshotEngine(fixture());
}

describe("static reader query contract", () => {
  it("applies cross-dimension AND and topic OR before sorting and pagination", async () => {
    const api = await engine();
    expect(api.papers({ direction: "agent,llm", level: "A", sort: "citation_desc", page: 1, size: 1 })).toMatchObject({ total: 2, items: [{ id: 35 }] });
    expect(api.papers({ direction: "llm,agent", level: "A", sort: "citation_desc", page: 2, size: 1 }).items.map((p) => p.id)).toEqual([11]);
    expect(api.papers({ access: "official" }).items.map((p) => p.id)).toEqual([23]);
    expect(api.papers({ venue: "BJ", year: "2024" }).total).toBe(1);
    expect(api.papers({ direction: "unknown" }).total).toBe(0);
    expect(api.papers({ size: 5 }).size).toBe(5);
  });
  it("searches full abstracts with English stemming, AND semantics and stable sorting", async () => {
    const api = await engine();
    expect(api.search({ q: "accelerate inference", sort: "citation_desc" }).items.map((p) => p.id)).toEqual([35, 11]);
    expect(api.search({ q: "models planning" }).items.map((p) => p.id)).toEqual([23]);
    expect(api.search({ q: "speculative agents" }).total).toBe(0);
    expect(api.search({ q: "model", sort: "year_desc", size: 1 }).items[0].id).toBe(35);
    expect(api.search({ q: "unfindable" }).total).toBe(0);
  });
  it.each([{ page: 0 }, { size: 101 }, { level: "C" }, { type: "workshop" }, { year: "20x4" }, { access: "bad" }, { sort: "unknown" }, { direction: "agent," }])("rejects invalid filters %j", async (params) => {
    expect(() => ({})).not.toThrow();
    const api = await engine();
    expect(() => api.papers(params)).toThrow();
  });
  it.each(["中文检索", "?!", "word ".repeat(25), "a".repeat(301)])("rejects invalid search instead of showing all papers", async (q) => {
    const api = await engine();
    expect(() => api.search({ q })).toThrow();
  });
  it("keeps dashboard counts and zero-venue scope consistent", async () => {
    const api = await engine();
    const stats = api.dashboard({ direction: "agent" });
    expect(stats).toMatchObject({ total: 2, configured_venues: 3, venues_with_papers: 2, with_oa_link: 1, recent_count: 1, generated_at });
    expect(stats.directions.find((d) => d.code === "agent").paper_count).toBe(2);
    expect(stats.directions.find((d) => d.code === "llm").paper_count).toBe(1);
    expect(stats.venues.find((v) => v.abbr === "EMPTY").paper_count).toBe(0);
    expect(api.dashboard({ level: "B" }).configured_venues).toBe(2);
    expect(stats.annual.map((year) => year.year)).toEqual([2023, 2024, 2025, 2026]);
  });
  it("reconstructs details and preserves backend-independent external links", async () => {
    const api = await engine();
    expect(api.paper("11")).toMatchObject({ venue: { abbr: "AC", type: "conf", level: "A" }, authors: [{ name: "Ada", order: 1 }], directions: [{ code: "llm" }, { code: "agent" }], official_url: "https://doi.org/10.5555/paper.11" });
    expect(api.paper(11).abstract.length).toBeGreaterThan(360);
    expect(() => api.paper("404")).toThrow("论文不存在");
    expect(() => api.trigger({ scope: "weekly" })).toThrow("只读");
    expect(api.crawlStatus()).toMatchObject({ mode: "snapshot", read_only: true, schedule: null });
  });
  it("defaults to publication dates, falls back to year and keeps details out of list transfers", async () => {
    const { createSnapshotEngine } = await import("./snapshot-engine.js");
    const data = fixture();
    data.papers[0].publication_date = "2026-05-01";
    data.papers[1].publication_date = "2026-05-01";
    data.papers[2].publication_date = "invalid";
    const api = createSnapshotEngine(data);
    expect(api.papers().items.map((p) => p.id)).toEqual([23, 11, 35]);
    expect(api.papers({ sort: "created_desc" }).items.map((p) => p.id)).toEqual([35, 11, 23]);
    expect(api.search({ q: "model", sort: "publication_desc" }).items.map((p) => p.id)).toEqual([23, 11, 35]);
    expect(api.papers().items[0]).not.toHaveProperty("abstract");
    expect(api.paper(23).abstract).toBe("A model planning system");
  });
  it("rejects duplicate ids instead of silently replacing paper details", async () => {
    const { createSnapshotEngine } = await import("./snapshot-engine.js");
    const data = fixture();
    data.papers.push(data.papers[0]);
    data.manifest.paper_count += 1;
    expect(() => createSnapshotEngine(data)).toThrow();
  });
});

it("ranks exact titles first without dropping nonadjacent AND matches", async () => {
  const { createSnapshotEngine } = await import("./snapshot-engine.js");
  const data = fixture();
  data.papers[0].title = "Alpha with Distributed Omega";
  data.papers[0].abstract = "Short summary";
  data.papers[1].title = "Alpha Omega";
  data.papers[1].abstract = "Short summary";
  data.papers[2].title = "Unrelated title";
  data.papers[2].abstract = "alpha omega ".repeat(100);
  const api = createSnapshotEngine(data);
  expect(api.search({ q: "alpha omega" }).items.map((p) => p.id)).toEqual([
    data.papers[1].id, data.papers[0].id, data.papers[2].id,
  ]);
});

it("normalizes diacritics in a complete title query", async () => {
  const { createSnapshotEngine } = await import("./snapshot-engine.js");
  const data = fixture();
  data.papers[0].title = "A Naïve Approach to Inference";
  const api = createSnapshotEngine(data);
  expect(api.search({ q: data.papers[0].title }).items.map((p) => p.id)).toEqual([data.papers[0].id]);
});


it("recovers exact Unicode titles even when word tokenization differs", async () => {
  const { createSnapshotEngine } = await import("./snapshot-engine.js");
  const data = fixture();
  data.papers[0].title = "λDiff: A New Model for Inference";
  const api = createSnapshotEngine(data);
  expect(api.search({ q: data.papers[0].title }).items[0].id).toBe(data.papers[0].id);
  for (const q of ['λDiff', 'λDiff inference', 'diff inference']) {
    expect(api.search({ q }).items.some((paper) => paper.id === data.papers[0].id)).toBe(true);
  }
});

it('accepts existing long complete titles without unbounding arbitrary queries', async () => {
  const { createSnapshotEngine } = await import('./snapshot-engine.js');
  const data = fixture();
  data.papers[0].title = Array.from({ length: 40 }, (_, i) => `ScientificTerm${i}`).join(' ');
  const api = createSnapshotEngine(data);
  expect(api.search({ q: data.papers[0].title }).items[0].id).toBe(data.papers[0].id);
  expect(() => api.search({ q: 'unrecognized '.repeat(30) })).toThrow();
});


it('keeps known complete titles valid when filters exclude the paper', async () => {
  const { createSnapshotEngine } = await import('./snapshot-engine.js');
  for (const title of [Array.from({ length: 40 }, (_, i) => `ScientificTerm${i}`).join(' '), 'Visual Grounding 中文 Benchmark']) {
    const data = fixture();
    data.papers[0].title = title;
    const api = createSnapshotEngine(data);
    expect(api.search({ q: title, year: data.papers[0].year + 1 })).toMatchObject({ total: 0, items: [] });
  }
});

it.each(["spec dec", "SPEC DEC", "  SpEc   DeC  ", "ＳＰＥＣ ＤＥＣ"])("matches multiple fragments without case sensitivity: %s", async (q) => {
  const api = await engine();
  for (const match of ["auto", "fuzzy"]) {
    expect(api.search({ q, match }).items.some(paper => paper.id === 11)).toBe(true);
    expect(api.search({ q, match, level: "B" }).total).toBe(0);
  }
  expect(api.search({ q, match: "keywords" }).total).toBe(0);
});
