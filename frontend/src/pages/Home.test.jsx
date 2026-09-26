import { render, screen } from "@testing-library/react";
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
