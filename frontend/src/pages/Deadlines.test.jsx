import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Deadlines from "./Deadlines.jsx";
import { loadDeadlineFeed } from "../lib/deadlines.js";
vi.mock("../lib/deadlines.js", async () => ({ ...await vi.importActual("../lib/deadlines.js"), loadDeadlineFeed: vi.fn() }));
const makeEvent = (id, venue, level, deadline) => ({ id, venue, level, year: 2027, venue_name: `${venue} Conference`, area: "人工智能", round: "第一轮", deadline_utc: deadline, abstract_deadline_utc: null, timezone: "AoE", link: "https://conference.example.org/", source_url: "https://github.com/ccfddl/ccf-deadlines" });
beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-01T00:00:00Z"));
  loadDeadlineFeed.mockResolvedValue({ version: 1, generated_at: "2026-10-01T00:00:00Z", source: { url: "https://github.com/ccfddl/ccf-deadlines" }, coverage: { matched_conferences: 3, configured_conferences: 4, missing_venues: ["OSDI"] }, events: [
    makeEvent("past", "PAST", "A", "2026-09-29T12:00:00Z"),
    makeEvent("a", "WWW", "A", "2026-10-02T12:00:00Z"),
    makeEvent("b", "WSDM", "B", "2026-10-02T16:00:00Z"),
    makeEvent("tba", "TBA", "B", null),
  ] });
});
afterEach(() => vi.restoreAllMocks());
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: 0, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><Deadlines /></MemoryRouter></QueryClientProvider>);
}
it("shows only future rounds by default and combines calendar and grade filters", async () => {
  mount();
  expect(await screen.findByRole("heading", { name: "WWW 2027" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "PAST 2027" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "B 类会议" }));
  expect(screen.queryByRole("heading", { name: "WWW 2027" })).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "WSDM 2027" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "2026-10-03，1 个截稿节点" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("日历时区"), { target: { value: "UTC" } });
  expect(screen.getByRole("button", { name: "2026-10-02，1 个截稿节点" })).toBeInTheDocument();
});
it("offers unknown deadlines honestly without a fabricated calendar event", async () => {
  mount();
  await screen.findByRole("heading", { name: "WWW 2027" });
  fireEvent.click(screen.getByRole("button", { name: "待公布" }));
  expect(screen.getByRole("heading", { name: "TBA 2027" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "导出当前结果 .ics" })).toBeDisabled();
  expect(screen.getByText(/OSDI/)).toBeInTheDocument();
});
it("shows a retryable calendar error independently of the paper database", async () => {
  loadDeadlineFeed.mockRejectedValue(new Error("截稿数据不可用"));
  mount();
  expect(await screen.findByText("截稿数据不可用")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
});
