import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import Home from "./Home.jsx";
import { api } from "../api.js";
import { snapshotFixture } from "../test/snapshot-fixture.js";
import { createSnapshotEngine } from "../data/snapshot-engine.js";

vi.mock("../api.js", () => ({ api: {
  isSnapshot: true, dashboard: vi.fn(), latest: vi.fn(), papers: vi.fn(), venueTopics: vi.fn(),
} }));

beforeEach(() => {
  vi.clearAllMocks();
  api.venueTopics.mockResolvedValue({ items: {} });
});

function renderOverview(fixture = snapshotFixture()) {
  const engine = createSnapshotEngine(fixture);
  api.dashboard.mockImplementation(async params => engine.dashboard(params));
  api.latest.mockImplementation(async params => engine.latest(params));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={client}><Home /></QueryClientProvider></MemoryRouter>);
  return engine;
}

it("uses the lightweight latest endpoint rather than fetching the full paper library", async () => {
  renderOverview();
  expect(await screen.findByRole("link", { name: "Speculative model" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "最新发表" })).toBeInTheDocument();
  expect(api.latest).toHaveBeenCalledTimes(1);
  expect(api.papers).not.toHaveBeenCalled();
});

it("keeps the overview focused on statistics without duplicating the venue directory", async () => {
  renderOverview();
  expect(await screen.findByRole("heading", { name: "年度收录分布" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "研究主题分布" })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "CCF 顶会与顶刊" })).not.toBeInTheDocument();
  expect(screen.queryByRole("searchbox", { name: "搜索会议期刊" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "浏览会议与期刊" })).toHaveAttribute("href", "/venues");
  expect(api.venueTopics).not.toHaveBeenCalled();
  expect(api.papers).not.toHaveBeenCalled();
});

it("retains all four scope filters and updates overview statistics after removing the directory", async () => {
  const fixture = snapshotFixture();
  fixture.catalog.venues.push(
    { id: 401, abbr: "BC", name: "B Conference", level: "B", type: "conf", ccf_area: "Systems", active: 1 },
    { id: 402, abbr: "AJ", name: "A Journal", level: "A", type: "journal", ccf_area: "Systems", active: 1 },
  );
  const engine = renderOverview(fixture);
  await screen.findByRole("region", { name: "论文库概览" });
  for (const [label, level, type] of [["A 类会议", "A", "conf"], ["B 类会议", "B", "conf"], ["A 类期刊", "A", "journal"], ["B 类期刊", "B", "journal"]]) {
    fireEvent.click(screen.getByRole("button", { name: label, exact: true }));
    await waitFor(() => expect(api.dashboard).toHaveBeenCalledWith({ level, type }, expect.any(AbortSignal)));
    await waitFor(() => {
      const overview = screen.getByRole("region", { name: "论文库概览" });
      const count = within(overview).getByText("已收录论文").closest(".metric-card").querySelector(".metric-value");
      expect(count).toHaveTextContent(new RegExp(`^${engine.dashboard({ level, type }).total}$`));
    });
    expect(screen.getByRole("button", { name: label, exact: true })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("region", { name: "CCF 顶会与顶刊" })).not.toBeInTheDocument();
  }
  expect(api.venueTopics).not.toHaveBeenCalled();
  expect(api.papers).not.toHaveBeenCalled();
});
