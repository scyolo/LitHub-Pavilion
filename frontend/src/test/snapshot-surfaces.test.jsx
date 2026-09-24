import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HashRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createSnapshotEngine } from "../data/snapshot-engine.js";
import { snapshotFixture } from "./snapshot-fixture.js";
import { api } from "../api.js";
import Admin from "../pages/Admin.jsx";
import PaperList from "../pages/PaperList.jsx";
import PaperDetail from "../pages/PaperDetail.jsx";

vi.mock("../api.js", () => ({ api: { isSnapshot: true, papers: vi.fn(), paper: vi.fn(), search: vi.fn(), dashboard: vi.fn(), crawlStatus: vi.fn(), crawlLogs: vi.fn(), trigger: vi.fn(), refreshSnapshot: vi.fn(async () => false), getSnapshotState: vi.fn(), subscribeSnapshot: () => () => {} } }));

function renderReader(path) {
  window.location.hash = path;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}><HashRouter><Routes><Route path="/admin" element={<Admin />} /><Route path="/papers" element={<PaperList />} /><Route path="/papers/:id" element={<PaperDetail />} /></Routes></HashRouter></QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  const data = snapshotFixture();
  const engine = createSnapshotEngine(data);
  const state = { status: "ready", revision: data.manifest.revision, generated_at: data.manifest.generated_at, error: null };
  api.getSnapshotState.mockReturnValue(state);
  for (const method of ["papers", "paper", "search", "dashboard", "crawlStatus", "crawlLogs"]) api[method].mockImplementation(async (params) => engine[method](params));
});

describe("backend-free reader surfaces", () => {
  it("shows an honest read-only synchronization page without executable collection controls", async () => {
    renderReader("/admin");
    expect(await screen.findByText("静态快照 · 只读")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "立即同步元数据" })).not.toBeInTheDocument();
    expect(screen.queryByText("当前空闲")).not.toBeInTheDocument();
    expect(screen.queryByText("每周一 04:00")).not.toBeInTheDocument();
    expect(api.trigger).not.toHaveBeenCalled();
  });
  it("supports scope changes, details and direct original-paper links under hash routing", async () => {
    renderReader("/papers?direction=agent&sort=citation_desc");
    const title = await screen.findByRole("link", { name: "Agents in planning" });
    expect(title).toHaveAttribute("href", "#/papers/23");
    fireEvent.click(title);
    expect(await screen.findByRole("heading", { name: "Agents in planning" })).toBeInTheDocument();
    expect(screen.getByText("A model planning system")).toBeInTheDocument();
    const official = screen.getByRole("link", { name: "访问官方页面" });
    expect(official).toHaveAttribute("href", "https://doi.org/10.5555/paper.23");
    expect(official).toHaveAttribute("target", "_blank");
    expect(official.getAttribute("rel")).toContain("noopener");
    fireEvent.click(screen.getByRole("link", { name: "返回论文探索" }));
    expect(await screen.findByRole("link", { name: "Agents in planning" })).toBeInTheDocument();
    expect(window.location.hash).toContain("direction=agent");
    fireEvent.change(screen.getByLabelText("论文归属年份"), { target: { value: "2025" } });
    expect(await screen.findByText("1 篇论文")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Agents in planning" })).not.toBeInTheDocument();
  });
  it("searches within the snapshot and clears the query without showing stale results", async () => {
    renderReader("/papers");
    expect(await screen.findByText("3 篇论文")).toBeInTheDocument();
    const search = screen.getByRole("searchbox", { name: "搜索论文" });
    fireEvent.change(search, { target: { value: "planning" } });
    fireEvent.submit(search.closest("form"));
    expect(await screen.findByText("1 篇论文")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Agents in planning" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Speculative model" })).not.toBeInTheDocument();
    expect(window.location.hash).toContain("q=planning");
    fireEvent.click(screen.getByRole("button", { name: "清空搜索" }));
    expect(await screen.findByText("3 篇论文")).toBeInTheDocument();
    expect(window.location.hash).not.toContain("q=");
  });
  it("combines scope and open-access filters and reports a true empty result", async () => {
    renderReader("/papers");
    await screen.findByText("3 篇论文");
    fireEvent.click(screen.getByRole("button", { name: "B 类期刊", exact: true }));
    expect(await screen.findByText("1 篇论文")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Agents in planning" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "有开放版本链接" }));
    expect(await screen.findByText("0 篇论文")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Agents in planning" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "清除所有筛选" }));
    expect(await screen.findByText("3 篇论文")).toBeInTheDocument();
  });
  it("paginates deterministically and resets the page when filters change", async () => {
    const fixture = snapshotFixture();
    const template = fixture.papers[0];
    fixture.papers = Array.from({ length: 25 }, (_, i) => ({ ...template, id: i + 1, title: `Paper ${i + 1}`, citation_count: i }));
    fixture.manifest.paper_count = 25;
    const engine = createSnapshotEngine(fixture);
    api.papers.mockImplementation(async (params) => engine.papers(params));
    api.dashboard.mockImplementation(async (params) => engine.dashboard(params));
    renderReader("/papers?size=10&sort=citation_desc");
    await screen.findByRole("link", { name: "Paper 25", exact: true });
    fireEvent.click(screen.getByRole("button", { name: "下一页", exact: true }));
    expect(await screen.findByRole("link", { name: "Paper 15", exact: true })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Paper 25", exact: true })).not.toBeInTheDocument();
    expect(window.location.hash).toContain("page=2");
    fireEvent.change(screen.getByLabelText("论文归属年份"), { target: { value: "2025" } });
    expect(await screen.findByRole("link", { name: "Paper 25", exact: true })).toBeInTheDocument();
    await waitFor(() => expect(window.location.hash).not.toContain("page="));
    expect(screen.getByRole("button", { name: "上一页", exact: true })).toBeDisabled();
  });
  it("shows missing-paper errors without replacing them with another paper", async () => {
    renderReader("/papers/404");
    expect(await screen.findByText("论文不存在")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "访问官方页面" })).not.toBeInTheDocument();
  });
});
