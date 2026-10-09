import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { TopicChart, VenueCoverage } from "./Charts.jsx";

const directions = Array.from({ length: 16 }, (_, index) => ({
  code: `test-topic-${index}`, name: `测试方向 ${index + 1}`, paper_count: (index + 1) * 10,
}));

it("keeps every direction in a named, keyboard-focusable scroll region", () => {
  const select = vi.fn();
  render(<TopicChart data={directions} onSelect={select} />);
  const list = screen.getByRole("region", { name: "研究主题列表" });
  expect(list).toHaveAttribute("tabindex", "0");
  expect(screen.getByText("共 16 个方向 · 滚动查看全部")).toBeInTheDocument();
  const buttons = within(list).getAllByRole("button");
  expect(buttons).toHaveLength(16);
  expect(buttons[0]).toHaveAccessibleName("查看测试方向 16，160篇");
  expect(buttons.at(-1)).toHaveAccessibleName("查看测试方向 1，10篇");
  fireEvent.click(buttons.at(-1));
  expect(select).toHaveBeenCalledWith("test-topic-0");
});

it("preserves keyboard activation of directions after the scroll region", async () => {
  const select = vi.fn();
  const user = userEvent.setup();
  render(<TopicChart data={directions} onSelect={select} />);
  await user.tab();
  expect(screen.getByRole("region", { name: "研究主题列表" })).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("button", { name: "查看测试方向 16，160篇" })).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(select).toHaveBeenCalledWith("test-topic-15");
});

it("does not promise more data or add a scroll tab stop for an empty distribution", () => {
  render(<TopicChart onSelect={vi.fn()} />);
  expect(screen.getByText("暂无方向数据")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "研究主题列表" })).not.toHaveAttribute("tabindex");
  expect(screen.queryByText(/滚动查看全部/)).not.toBeInTheDocument();
});

it("keeps zero-count directions instead of hiding sparse data", () => {
  render(<TopicChart data={[{ code: "unused", name: "未收录", paper_count: 0 }]} onSelect={vi.fn()} />);
  expect(screen.getByRole("button", { name: "查看未收录，0篇" })).toBeInTheDocument();
  expect(screen.queryByText(/滚动查看全部/)).not.toBeInTheDocument();
});

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
