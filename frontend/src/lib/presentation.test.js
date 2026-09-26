import { describe, expect, it } from "vitest";
import { paperLinks, parseFilters, percent, publicationSortKey, safeExternalUrl } from "./presentation.js";

describe("link-only presentation", () => {
  it.each(["javascript:alert(1)", "data:text/html,test", "https://localhost/a", "https://localhost./a", "https://printer.localdomain/a", "http://127.0.0.1/x", "https://10.0.0.1/a", "https://name:secret@example.org", "file:///x"])("rejects unsafe external URLs: %s", (url) => {
    expect(safeExternalUrl(url)).toBeNull();
  });
  it("retains legitimate sources and arxiv fallback", () => {
    expect(safeExternalUrl("https://doi.org/10.1234/example")).toBe("https://doi.org/10.1234/example");
    expect(paperLinks({ arxiv_id: "2506.08373", official_url: "https://example.org/paper" })).toEqual({ official: "https://example.org/paper", oa: "https://arxiv.org/abs/2506.08373" });
  });
  it.each(["http://100.64.0.1/paper", "http://198.19.0.1/paper", "http://224.0.0.1/", "http://240.0.0.1/", "https://publisher.example/%0aheader", "https://publisher.example/a%xx", "https://publisher.example/a\\b", "https://intranet/paper"]) ("rejects reserved addresses and malformed URL %s", (url) => {
    expect(safeExternalUrl(url)).toBeNull();
  });
  it("reconstructs stable DOI, DBLP and legacy arXiv links without a backend", () => {
    expect(paperLinks({ doi: "https://doi.org/10.5555/Example" }).official).toBe("https://doi.org/10.5555/example");
    expect(paperLinks({ doi: "doi: 10.5555/a#fragment" }).official).toBe("https://doi.org/10.5555/a%23fragment");
    expect(paperLinks({ dblp_key: "conf/nips/Example24" }).official).toBe("https://dblp.org/rec/conf/nips/Example24");
    expect(paperLinks({ arxiv_id: "cs/9901001" }).oa).toBe("https://arxiv.org/abs/cs/9901001");
    expect(paperLinks({ arxiv_id: "https://arxiv.org/pdf/2501.12345v2.pdf" }).oa).toBe("https://arxiv.org/abs/2501.12345v2");
  });
  it("does not invent destinations from unsafe or incomplete identifiers", () => {
    expect(paperLinks({ doi: "https://attacker.example/10.5555/id", dblp_key: "conf/nips/../../private", arxiv_id: "2513.12345" })).toEqual({ official: null, oa: null });
  });
  it("handles zero totals honestly", () => expect(percent(0, 0)).toBe("—"));
});

describe("publication dates", () => {
  it.each([
    ["2026-03-02", 2024, "2026-03-02"], ["2024-02-29", 2025, "2024-02-29"],
    ["2025-02-29", 2026, "2026-00-00"], ["2026-04-31", 2025, "2025-00-00"],
    [null, 2026, "2026-00-00"], ["2026-03", 2024, "2024-00-00"],
    ["2026-01-01T00:00:00Z", 2025, "2025-00-00"], [null, null, ""],
  ])("validates %s with year %s", (publication_date, year, expected) => {
    expect(publicationSortKey({ publication_date, year })).toBe(expected);
  });
});

describe("filter URL state", () => {
  it("normalizes unsupported sort modes", () => {
    expect(parseFilters("sort=unknown").sort).toBe("publication_desc");
    expect(parseFilters("q=agent&sort=unknown").sort).toBe("relevance");
  });
  it.each(["abc", "NaN", "-1", "0", "1.5"])("normalizes invalid page %s", (page) => expect(parseFilters(`page=${page}`).page).toBe(1));
  it("keeps A/B only and supports type/access", () => {
    expect(parseFilters("level=C&type=other&size=500")).toMatchObject({ level: "", type: "", size: 20 });
    expect(parseFilters("level=B&type=journal&access=oa&direction=llm,cv&page=3")).toMatchObject({ level: "B", type: "journal", access: "oa", direction: "llm,cv", page: 3 });
  });
  it("defaults search sort to relevance", () => expect(parseFilters("q=agent").sort).toBe("relevance"));
});
