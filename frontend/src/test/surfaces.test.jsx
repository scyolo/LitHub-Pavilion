import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Admin from "../pages/Admin.jsx";
import PaperCard from "../components/PaperCard.jsx";
import { AnnualChart } from "../components/Charts.jsx";

vi.mock("../api.js", () => ({ api: {
  crawlStatus: vi.fn(async () => ({ running: false, schedule: null })),
  dashboard: vi.fn(async () => ({ total: 2, with_abstract: 1, with_oa_link: 1, venues_with_papers: 1, configured_venues: 2 })),
  crawlLogs: vi.fn(async () => ({ total: 0, items: [] })),
  trigger: vi.fn(async () => ({ run_id: "test-run" })),
} }));

function wrapper({ children }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return <MemoryRouter><QueryClientProvider client={client}>{children}</QueryClientProvider></MemoryRouter>;
}

beforeEach(() => vi.clearAllMocks());

describe("new research surfaces", () => {
  it("renders the management page without the old status TDZ crash", async () => {
    render(<Admin />, { wrapper });
    expect(await screen.findByText("当前空闲")).toBeInTheDocument();
    expect(await screen.findByText("暂无采集日志。可以手动同步一次元数据。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /下载.*PDF/ })).not.toBeInTheDocument();
  });
  it("keeps external paper links separate from detail navigation", () => {
    const paper = { id: 74, title: "A Study of Agents", venue: "AAAI", venue_type: "conf", year: 2025, level: "A", directions: ["agent"], authors_preview: ["Author One"], authors_count: 1, citation_count: 2, official_url: "https://doi.org/10.1/test", oa_url: "https://arxiv.org/abs/2501.12345", venue_confirmed: 0 };
    render(<PaperCard paper={paper} />, { wrapper });
    expect(screen.getByRole("link", { name: paper.title })).toHaveAttribute("href", "/papers/74");
    expect(screen.getByRole("link", { name: "官方链接" })).toHaveAttribute("target", "_blank");
    expect(screen.getByText("归属待核验")).toBeInTheDocument();
  });
  it("exposes an interactive, keyboard-operable chart without fabricated values", () => {
    const select = vi.fn();
    render(<AnnualChart data={[{ year: 2023, A: 0, B: 0, total: 0 }, { year: 2024, A: 7, B: 3, total: 10 }]} onSelect={select} />);
    fireEvent.click(screen.getByRole("button", { name: "筛选 2024 年论文，共 10 篇" }));
    expect(select).toHaveBeenCalledWith("2024");
    expect(screen.getByRole("img")).toHaveAccessibleName("2023年：A类0篇、B类0篇；2024年：A类7篇、B类3篇");
  });
});
