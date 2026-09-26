import { act, render, screen, waitFor } from "@testing-library/react";
import { useQuery } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import DataSession from "./DataSession.jsx";

const mock = vi.hoisted(() => ({
  source: { source: "snapshot", generation: 0 },
  snapshot: { status: "ready", revision: "one", generated_at: "2026-09-22T00:00:00Z" },
  sourceListeners: new Set(), snapshotListeners: new Set(),
  check: vi.fn(async () => false), refresh: vi.fn(async () => false), query: vi.fn(),
}));
vi.mock("../api.js", () => ({ api: {
  isAuto: true,
  getDataState: () => mock.source,
  subscribeData: (listener) => { mock.sourceListeners.add(listener); return () => mock.sourceListeners.delete(listener); },
  getSnapshotState: () => mock.snapshot,
  subscribeSnapshot: (listener) => { mock.snapshotListeners.add(listener); return () => mock.snapshotListeners.delete(listener); },
  checkConnection: mock.check, refreshSnapshot: mock.refresh,
} }));

function Reader() {
  const query = useQuery({ queryKey: ["same-record"], queryFn: mock.query });
  return <p>{query.data || "Loading"}</p>;
}

beforeEach(() => {
  vi.clearAllMocks();
  mock.source = { source: "snapshot", generation: 0 };
  mock.snapshot = { status: "ready", revision: "one", generated_at: "2026-09-22T00:00:00Z" };
  mock.sourceListeners.clear(); mock.snapshotListeners.clear();
});
afterEach(() => vi.useRealTimers());

it("replaces query caches across complete revisions and API recovery without mixing records", async () => {
  mock.query.mockResolvedValue("Snapshot one");
  render(<DataSession><Reader /></DataSession>);
  expect(await screen.findByText("Snapshot one")).toBeInTheDocument();
  mock.query.mockResolvedValue("Snapshot two");
  act(() => {
    mock.snapshot = { ...mock.snapshot, revision: "two" };
    for (const notify of mock.snapshotListeners) notify();
  });
  expect(await screen.findByText("Snapshot two")).toBeInTheDocument();
  expect(screen.queryByText("Snapshot one")).not.toBeInTheDocument();
  mock.query.mockResolvedValue("Live record");
  act(() => {
    mock.source = { source: "api", generation: 1 };
    for (const notify of mock.sourceListeners) notify();
  });
  expect(await screen.findByText("Live record")).toBeInTheDocument();
  expect(screen.queryByText("Snapshot two")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "连接本地后端" })).not.toBeInTheDocument();
});

it("keeps the first query client when catalog and full data become ready", async () => {
  mock.snapshot = { status: "loading", revision: null, generation: 0 };
  mock.query.mockResolvedValue("Initial record");
  render(<DataSession><Reader /></DataSession>);
  await screen.findByText("Initial record");
  for (const verification of ["catalog", "full"]) {
    act(() => {
      mock.snapshot = { ...mock.snapshot, status: "ready", revision: "one", generation: 0, verification };
      for (const notify of mock.snapshotListeners) notify();
    });
  }
  expect(mock.query).toHaveBeenCalledTimes(1);
});

it("checks connection on focus and cleans up listeners when unmounted", async () => {
  mock.query.mockResolvedValue("Ready");
  const view = render(<DataSession><Reader /></DataSession>);
  await screen.findByText("Ready");
  const count = mock.check.mock.calls.length;
  act(() => window.dispatchEvent(new Event("focus")));
  await waitFor(() => expect(mock.check.mock.calls.length).toBe(count + 1));
  view.unmount();
  const after = mock.check.mock.calls.length;
  window.dispatchEvent(new Event("focus"));
  expect(mock.check.mock.calls.length).toBe(after);
  expect(mock.sourceListeners.size).toBe(0);
  expect(mock.snapshotListeners.size).toBe(0);
});
