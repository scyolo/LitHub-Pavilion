import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "../App.jsx";
import { api } from "../api.js";
import { createSnapshotEngine } from "../data/snapshot-engine.js";
import { snapshotFixture } from "./snapshot-fixture.js";

vi.mock("../api.js", () => ({ api: {
  isSnapshot: true, dashboard: vi.fn(), latest: vi.fn(), directions: vi.fn(), crawlStatus: vi.fn(),
} }));
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  const engine = createSnapshotEngine(snapshotFixture());
  for (const method of ["dashboard", "latest", "directions", "crawlStatus"]) api[method].mockImplementation(async params => engine[method](params));
});
afterEach(() => { localStorage.clear(); delete document.documentElement.dataset.theme; });

it("synchronizes the cover, global theme and saved preference without refetching papers", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><MemoryRouter><App /></MemoryRouter></QueryClientProvider>);
  const cover = await screen.findByRole("region", { name: /东方神话封面/ });
  await screen.findByRole("link", { name: "Speculative model", exact: true });
  const calls = api.latest.mock.calls.length;
  expect(cover).toHaveAttribute("data-realm", "stars");
  fireEvent.click(screen.getByRole("button", { name: "切换至鸿蒙云海", exact: true }));
  await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", "light"));
  expect(cover).toHaveAttribute("data-realm", "heaven");
  expect(localStorage.getItem("papertracker-theme")).toBe("light");
  fireEvent.click(screen.getByRole("button", { name: "切换深色主题", exact: true }));
  await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", "dark"));
  expect(cover).toHaveAttribute("data-realm", "stars");
  expect(localStorage.getItem("papertracker-theme")).toBe("dark");
  expect(api.latest).toHaveBeenCalledTimes(calls);
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
});
