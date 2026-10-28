import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Industry from "./Industry.jsx";
import { loadIndustryFeed } from "../lib/industry.js";
vi.mock("../lib/industry.js", async () => ({ ...await vi.importActual("../lib/industry.js"), loadIndustryFeed: vi.fn() }));

const orgs = [
  { code: "deepseek", name: "深度求索", name_en: "DeepSeek", country: "中国", note: "通用大模型与开源推理模型", count: 2 },
  { code: "openai", name: "OpenAI", name_en: "OpenAI", country: "美国", note: "通用大模型与多模态系统", count: 1 },
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

beforeEach(() => loadIndustryFeed.mockResolvedValue(feed));
afterEach(() => vi.restoreAllMocks());

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: 0, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><Industry /></MemoryRouter></QueryClientProvider>);
}

it("lists DeepSeek first and filters by organization and report type", async () => {
  mount();
  expect(await screen.findByRole("heading", { name: "深度求索" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "OpenAI" })).toBeInTheDocument();
  expect(screen.getAllByText("DeepSeek-V3 Technical Report")).toHaveLength(1);

  fireEvent.click(screen.getByRole("button", { name: /OpenAI/ }));
  expect(screen.queryByRole("heading", { name: "深度求索" })).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "OpenAI" })).toBeInTheDocument();

  fireEvent.click(within(screen.getByRole("group", { name: "按机构筛选" })).getByRole("button", { name: /全部机构/ }));
  fireEvent.change(screen.getByLabelText("报告类型"), { target: { value: "journal_article" } });
  expect(screen.getByText("DeepSeek-R1 incentivizes reasoning in LLMs through reinforcement learning")).toBeInTheDocument();
  expect(screen.queryByText("GPT-4 Technical Report")).not.toBeInTheDocument();
});

it("searches titles and topics with the same static feed", async () => {
  mount();
  await screen.findByRole("heading", { name: "深度求索" });
  fireEvent.change(screen.getByLabelText("搜索大厂技术报告"), { target: { value: "推理" } });
  expect(screen.getByText("DeepSeek-R1 incentivizes reasoning in LLMs through reinforcement learning")).toBeInTheDocument();
  expect(screen.queryByText("GPT-4 Technical Report")).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "OpenAI" })).not.toBeInTheDocument();
});
