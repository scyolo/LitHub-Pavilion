import { describe, expect, it } from "vitest";
import { matchesText, normalizeSearchText, searchVenues } from "./search.js";

const venues = [
  { abbr: "NeurIPS", name: "Conference on Neural Information Processing Systems", ccf_area: "人工智能", paper_count: 12 },
  { abbr: "ICML", name: "International Conference on Machine Learning", ccf_area: "人工智能", paper_count: 50 },
  { abbr: "TPAMI", name: "IEEE Transactions on Pattern Analysis and Machine Intelligence", ccf_area: "人工智能", paper_count: 30 },
  { abbr: "SIGIR", name: "International ACM SIGIR Conference on Research and Development in Information Retrieval", ccf_area: "数据库/数据挖掘/内容检索", paper_count: 0 },
];

describe("case-insensitive fuzzy source search", () => {
  it("normalizes case, accents, full-width letters and punctuation without dropping Chinese", () => {
    expect(normalizeSearchText("  ＮＥＵＲ－ＩＰＳ / Café  人工智能  ")).toBe("neur ips cafe 人工智能");
  });

  it.each(["neurips", "NEURIPS", "NeUrIpS", "ＮｅｕｒＩＰＳ", "neur ips", "neur-ips", "NEUR"])("finds acronym fragments: %s", (query) => {
    expect(searchVenues(venues, query).map(v => v.abbr)).toEqual(["NeurIPS"]);
  });

  it.each(["nuerips", "neurps", "neuripss", "neurxps"])("tolerates one spelling edit: %s", (query) => {
    expect(searchVenues(venues, query)[0]?.abbr).toBe("NeurIPS");
  });

  it("ANDs separate fragments in any order across name and area", () => {
    expect(searchVenues(venues, "learning mach").map(v => v.abbr)).toEqual(["ICML"]);
    expect(searchVenues(venues, "人工智能 neural").map(v => v.abbr)).toEqual(["NeurIPS"]);
    expect(searchVenues(venues, "sig 检索").map(v => v.abbr)).toEqual(["SIGIR"]);
    expect(searchVenues(venues, "neural retrieval")).toEqual([]);
  });

  it("keeps exact acronym hits ahead of higher-volume approximate matches", () => {
    const noisy = [...venues, { ...venues[1], abbr: "ICME", name: "Multimedia Conference", paper_count: 500 }];
    expect(searchVenues(noisy, "icml").map(v => v.abbr)).toEqual(["ICML", "ICME"]);
  });

  it("does not typo-expand short acronyms or match an unrelated query", () => {
    expect(matchesText("AI", ["ML"])).toBe(false);
    expect(searchVenues(venues, "unrelatedsourcexyz")).toEqual([]);
    expect(searchVenues(venues, "？！")).toEqual([]);
  });

  it("keeps zero-record sources, handles missing fields and never mutates the catalog", () => {
    expect(searchVenues(venues, "  ", "name").map(v => v.abbr)).toEqual(["ICML", "NeurIPS", "SIGIR", "TPAMI"]);
    expect(searchVenues(venues).map(v => v.abbr)).toEqual(["ICML", "TPAMI", "NeurIPS", "SIGIR"]);
    expect(venues[0].abbr).toBe("NeurIPS");
    expect(matchesText("empty", [null, undefined, "EMPTY"])).toBe(true);
  });
});
