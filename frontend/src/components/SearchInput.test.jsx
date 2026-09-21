import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SearchInput from "./SearchInput.jsx";

afterEach(() => vi.useRealTimers());

describe("debounced search", () => {
  it("waits for IME composition to complete before searching", () => {
    vi.useFakeTimers(); const commit = vi.fn();
    render(<SearchInput value="" onCommit={commit} />);
    const input = screen.getByRole("searchbox");
    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "大模型" } });
    act(() => vi.advanceTimersByTime(1000));
    expect(commit).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input);
    expect(commit).toHaveBeenCalledExactlyOnceWith("大模型");
  });
  it("commits only the latest text after 450ms", () => {
    vi.useFakeTimers(); const commit = vi.fn();
    render(<SearchInput value="" onCommit={commit} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "agent" } });
    act(() => vi.advanceTimersByTime(200));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "agent planning" } });
    act(() => vi.advanceTimersByTime(449)); expect(commit).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1)); expect(commit).toHaveBeenCalledExactlyOnceWith("agent planning");
  });
  it("submits immediately on enter and cancels the scheduled call", () => {
    vi.useFakeTimers(); const commit = vi.fn();
    render(<SearchInput value="" onCommit={commit} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "llm" } });
    fireEvent.submit(screen.getByRole("search"));
    act(() => vi.advanceTimersByTime(1000)); expect(commit).toHaveBeenCalledExactlyOnceWith("llm");
  });
  it("restores a navigated URL value without stale submissions", () => {
    vi.useFakeTimers(); const commit = vi.fn();
    const { rerender } = render(<SearchInput value="agents" onCommit={commit} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "new pending search" } });
    rerender(<SearchInput value="decoding" onCommit={commit} />);
    act(() => vi.advanceTimersByTime(500));
    expect(screen.getByRole("searchbox")).toHaveValue("decoding"); expect(commit).not.toHaveBeenCalled();
  });
});
