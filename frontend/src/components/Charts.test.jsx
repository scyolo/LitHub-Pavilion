import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { TopicChart, VenueCoverage } from "./Charts.jsx";

it("shows every research direction rather than only the five largest", () => {
  render(<TopicChart data={Array.from({ length: 9 }, (_, index) => ({ code: `topic-${index}`, name: `Topic ${index}`, paper_count: 9 - index }))} onSelect={() => {}} />);
  expect(screen.getAllByRole("button")).toHaveLength(9);
});

it("links venue-year counts and distinguishes uncollected years", () => {
  const onSelect = vi.fn();
  render(<VenueCoverage venues={[{ abbr: "SIGIR", level: "A", type: "conf", paper_count: 42, years: [{ year: 2025, count: 42 }] }]} years={[{ year: 2025 }, { year: 2026 }]} onSelect={onSelect} />);
  fireEvent.click(screen.getByRole("button", { name: "SIGIR 2025 年 42 篇" }));
  expect(onSelect).toHaveBeenCalledWith({ venue: "SIGIR", year: "2025" });
  expect(screen.getByText("—")).toHaveAttribute("title", expect.stringContaining("暂无记录"));
});


it('bounds initial matrix rendering while preserving access to every configured source', () => {
  const venues=Array.from({length:40},(_,i)=>({abbr:'V'+String(i).padStart(2,'0'),level:'A',type:'conf',paper_count:40-i,years:[]}));
  render(<VenueCoverage venues={venues} years={[{year:2025}]} onSelect={()=>{}} />);
  expect(screen.getAllByRole('row')).toHaveLength(21);
  fireEvent.click(screen.getByRole('button',{name:'展开全部 40 个来源'}));
  expect(screen.getAllByRole('row')).toHaveLength(41);
  fireEvent.click(screen.getByRole('button',{name:'收起来源矩阵'}));
  expect(screen.getAllByRole('row')).toHaveLength(21);
});
