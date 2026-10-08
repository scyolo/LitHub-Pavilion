import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import Home from "./Home.jsx";
import { api } from "../api.js";
import { snapshotFixture } from "../test/snapshot-fixture.js";
import { createSnapshotEngine } from "../data/snapshot-engine.js";

vi.mock("../api.js", () => ({ api: { isSnapshot: true, dashboard: vi.fn(), latest: vi.fn(), papers: vi.fn() } }));
it("uses the lightweight latest endpoint rather than fetching the full paper library", async () => {
  const engine = createSnapshotEngine(snapshotFixture());
  api.dashboard.mockResolvedValue(engine.dashboard());
  api.latest.mockResolvedValue(engine.latest());
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={client}><Home /></QueryClientProvider></MemoryRouter>);
  expect(await screen.findByRole("link", { name: "Speculative model" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "最新发表" })).toBeInTheDocument();
  expect(api.latest).toHaveBeenCalledTimes(1);
  expect(api.papers).not.toHaveBeenCalled();
});


it("puts a searchable A/B conference and journal directory on the overview", async () => {
  const fixture = snapshotFixture();
  fixture.catalog.venues.push(
    { id: 401, abbr: "BC", name: "B Conference", level: "B", type: "conf", ccf_area: "Systems", active: 1 },
    { id: 402, abbr: "AJ", name: "A Journal", level: "A", type: "journal", ccf_area: "Systems", active: 1 },
  );
  const engine = createSnapshotEngine(fixture);
  api.dashboard.mockImplementation(async params => engine.dashboard(params));
  api.latest.mockImplementation(async params => engine.latest(params));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={client}><Home /></QueryClientProvider></MemoryRouter>);
  let directory = await screen.findByRole("region", { name: "CCF 顶会与顶刊" });
  expect(within(directory).getAllByRole("link", { name: /^浏览 .* 论文$/ })).toHaveLength(5);
  for (const [scope, abbr] of [["A 类会议", "AC"], ["B 类会议", "BC"], ["A 类期刊", "AJ"], ["B 类期刊", "BJ"]]) {
    fireEvent.click(screen.getByRole("button", { name: scope, exact: true }));
    directory = await screen.findByRole("region", { name: "CCF 顶会与顶刊" });
    expect(await within(directory).findByRole("link", { name: `浏览 ${abbr} 论文` })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: scope, exact: true })).toHaveAttribute("aria-pressed", "true");
  }
  const input = within(directory).getByRole("searchbox", { name: "搜索会议期刊" });
  fireEvent.change(input, { target: { value: "EmPtY" } });
  fireEvent.submit(input.closest("form"));
  expect(within(directory).getAllByRole("link", { name: /^浏览 .* 论文$/ })).toHaveLength(1);
  expect(within(directory).getByRole("link", { name: "浏览 EMPTY 论文" })).toBeInTheDocument();
  client.removeQueries({ queryKey: ["dashboard", { level: "A", type: "journal" }], exact: true });
  fireEvent.click(screen.getByRole("button", { name: "A 类期刊", exact: true }));
  directory = await screen.findByRole("region", { name: "CCF 顶会与顶刊" });
  expect(within(directory).getByRole("searchbox", { name: "搜索会议期刊" })).toHaveValue("EmPtY");
  expect(within(directory).getByRole("heading", { name: "没有匹配的会议或期刊" })).toBeInTheDocument();
  expect(api.papers).not.toHaveBeenCalled();
});
