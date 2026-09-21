import { describe, expect, it } from "vitest";
import { paperLinks, parseFilters, percent, safeExternalUrl } from "./presentation.js";

describe("link-only presentation", () => {
  it.each(["javascript:alert(1)", "data:text/html,test", "https://localhost/a", "https://localhost./a", "https://printer.localdomain/a", "http://127.0.0.1/x", "https://10.0.0.1/a", "https://name:secret@example.org", "file:///x"])("rejects unsafe external URLs: %s", (url) => {
    expect(safeExternalUrl(url)).toBeNull();
  });
  it("retains legitimate sources and arxiv fallback", () => {
    expect(safeExternalUrl("https://doi.org/10.1234/example")).toBe("https://doi.org/10.1234/example");
    expect(paperLinks({ arxiv_id: "2506.08373", official_url: "https://example.org/paper" })).toEqual({ official: "https://example.org/paper", oa: "https://arxiv.org/abs/2506.08373" });
  });
  it("handles zero totals honestly", () => expect(percent(0, 0)).toBe("—"));
});

describe("filter URL state", () => {
  it("normalizes unsupported sort modes", () => {
    expect(parseFilters("sort=unknown").sort).toBe("created_desc");
    expect(parseFilters("q=agent&sort=unknown").sort).toBe("relevance");
  });
  it.each(["abc", "NaN", "-1", "0", "1.5"])("normalizes invalid page %s", (page) => expect(parseFilters(`page=${page}`).page).toBe(1));
  it("keeps A/B only and supports type/access", () => {
    expect(parseFilters("level=C&type=other&size=500")).toMatchObject({ level: "", type: "", size: 20 });
    expect(parseFilters("level=B&type=journal&access=oa&direction=llm,cv&page=3")).toMatchObject({ level: "B", type: "journal", access: "oa", direction: "llm,cv", page: 3 });
  });
  it("defaults search sort to relevance", () => expect(parseFilters("q=agent").sort).toBe("relevance"));
});
