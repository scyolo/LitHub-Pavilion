import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { LinkCoverage } from "./Charts.jsx";
import PaperAccess from "./PaperAccess.jsx";

it("separates found full text from not-yet-found links without calling them closed", () => {
  const select = vi.fn();
  render(<LinkCoverage total={100} oa={37} onSelect={select} />);
  expect(screen.getByText("37%")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /已找到开放版本.*37/ }));
  expect(select).toHaveBeenLastCalledWith("oa");
  fireEvent.click(screen.getByRole("button", { name: /待发现开放版本.*63/ }));
  expect(select).toHaveBeenLastCalledWith("official");
  expect(screen.getByText(/未找到不代表没有开放版本/)).toBeInTheDocument();
});

it("keeps the empty coverage chart meaningful", () => {
  render(<LinkCoverage total={0} oa={0} onSelect={vi.fn()} />);
  expect(screen.getByText("—")).toBeInTheDocument();
  expect(screen.getAllByRole("button").every(button => button.disabled)).toBe(true);
});

it("does not count search destinations as verified open full text", () => {
  render(<PaperAccess paper={{ title: 'A & B: "Exact title"', doi: "10.1109/example.1" }} />);
  expect(screen.getByRole("link", { name: /访问官方页面/ })).toHaveAttribute("href", "https://doi.org/10.1109/example.1");
  expect(screen.queryByRole("link", { name: /阅读开放/ })).not.toBeInTheDocument();
  expect(screen.getByText(/检索入口不计入开放链接覆盖/)).toBeInTheDocument();
  const scholar = screen.getByRole("link", { name: /Google Scholar/ });
  expect(new URL(scholar.href).searchParams.get("q")).toBe('"A & B: "Exact title""');
  for (const link of screen.getAllByRole("link")) {
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  }
});

it("deduplicates official full text while still offering a separate preprint", () => {
  render(<PaperAccess paper={{ title: "A paper", official_url: "https://example.org/paper", oa_url: "https://example.org/paper", arxiv_id: "2501.12345" }} />);
  expect(screen.getAllByRole("link").filter(link => link.href === "https://example.org/paper")).toHaveLength(1);
  expect(screen.getByRole("link", { name: /阅读开放全文/ })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /arXiv 预印本/ })).toHaveAttribute("href", "https://arxiv.org/abs/2501.12345");
});
