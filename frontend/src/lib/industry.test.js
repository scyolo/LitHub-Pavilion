import { describe, expect, it } from "vitest";
import { filterReports, groupReports, kindLabel, validateIndustryFeed } from "./industry.js";

const orgs = [
  { code: "deepseek", name: "深度求索", name_en: "DeepSeek", country: "中国", note: "通用模型", count: 2 },
  { code: "openai", name: "OpenAI", name_en: "OpenAI", country: "美国", note: "多模态", count: 1 },
];
const reports = [
  { id: "deepseek-v3", org: "deepseek", title: "DeepSeek-V3 Technical Report", kind: "tech_report", year: 2024, published: "2024-12-27", url: "https://arxiv.org/abs/2412.19437", arxiv_id: "2412.19437", summary: "MoE 语言模型技术报告。", tags: ["LLM", "MoE"] },
  { id: "deepseek-r1-nature", org: "deepseek", title: "DeepSeek-R1 incentivizes reasoning in LLMs through reinforcement learning", kind: "journal_article", year: 2025, published: "2025-09-17", url: "https://doi.org/10.1038/s41586-025-09422-z", arxiv_id: null, summary: "推理模型的期刊论文。", tags: ["推理", "期刊"] },
  { id: "openai-gpt4", org: "openai", title: "GPT-4 Technical Report", kind: "tech_report", year: 2023, published: "2023-03-15", url: "https://arxiv.org/abs/2303.08774", arxiv_id: "2303.08774", summary: "多模态模型技术报告。", tags: ["LLM", "多模态"] },
];
const feed = {
  schema_version: 1, title: "大厂技术报告", generated_at: "2026-10-28T00:00:00Z", source_note: "独立目录",
  orgs, reports,
  stats: { reports: 3, orgs: 2, by_kind: { tech_report: 2, journal_article: 1 }, by_year: { 2023: 1, 2024: 1, 2025: 1 }, latest: "2025-09-17" },
};

describe("industry report feed", () => {
  it("accepts a consistent feed and rejects broken identities or links", () => {
    expect(validateIndustryFeed(feed).reports).toHaveLength(3);
    expect(() => validateIndustryFeed({ ...feed, schema_version: 2 })).toThrow();
    expect(() => validateIndustryFeed({ ...feed, reports: [reports[0], reports[0], reports[2]] })).toThrow();
    expect(() => validateIndustryFeed({ ...feed, reports: [{ ...reports[0], kind: "whitepaper" }, reports[1], reports[2]] })).toThrow();
    expect(() => validateIndustryFeed({ ...feed, reports: [{ ...reports[0], url: "javascript:alert(1)" }, reports[1], reports[2]] })).toThrow();
    expect(() => validateIndustryFeed({ ...feed, orgs: [orgs[0], { ...orgs[1], count: 2 }] })).toThrow();
  });

  it("filters by organization, type and fuzzy text without changing the feed order", () => {
    expect(filterReports(reports, orgs, { org: "deepseek" }).map(report => report.id)).toEqual(["deepseek-r1-nature", "deepseek-v3"]);
    expect(filterReports(reports, orgs, { kind: "tech_report" }).map(report => report.id)).toEqual(["deepseek-v3", "openai-gpt4"]);
    expect(filterReports(reports, orgs, { q: "OPEN AI" }).map(report => report.id)).toEqual(["openai-gpt4"]);
    expect(filterReports(reports, orgs, { q: "推理" }).map(report => report.id)).toEqual(["deepseek-r1-nature"]);
    expect(filterReports(reports, orgs, { q: "nonexistentxyz" })).toEqual([]);
  });

  it("groups only matching reports and orders groups by result size", () => {
    expect(groupReports(reports, orgs).map(group => [group.org.code, group.reports.length])).toEqual([["deepseek", 2], ["openai", 1]]);
    expect(groupReports(filterReports(reports, orgs, { kind: "tech_report" }), orgs).map(group => [group.org.code, group.reports.length])).toEqual([["deepseek", 1], ["openai", 1]]);
    expect(groupReports(filterReports(reports, orgs, { org: "openai" }), orgs)).toHaveLength(1);
    expect(kindLabel("journal_article")).toBe("期刊论文");
    expect(kindLabel("other")).toBe("other");
  });
});
