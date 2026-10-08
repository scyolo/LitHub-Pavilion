import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";
import VenueDirectory from "./VenueDirectory.jsx";

const venues = [
  { abbr: "NeurIPS", name: "Conference on Neural Information Processing Systems", level: "A", type: "conf", ccf_area: "人工智能", paper_count: 30, years: [{ year: 2025, count: 30 }] },
  { abbr: "ICML", name: "International Conference on Machine Learning", level: "A", type: "conf", ccf_area: "人工智能", paper_count: 20 },
  { abbr: "COLING", name: "International Conference on Computational Linguistics", level: "B", type: "conf", ccf_area: "人工智能", paper_count: 15 },
  { abbr: "TPAMI", name: "IEEE Transactions on Pattern Analysis and Machine Intelligence", level: "A", type: "journal", ccf_area: "人工智能", paper_count: 10 },
  { abbr: "TOIS", name: "ACM Transactions on Information Systems", level: "B", type: "journal", ccf_area: "数据库/数据挖掘/内容检索", paper_count: 0 },
];

function DirectoryHarness(props) {
  const [filters, setFilters] = useState({ search: "", sort: "count", area: "" });
  return <VenueDirectory venues={venues} filters={filters} onFiltersChange={setFilters} {...props} />;
}
function renderDirectory(props = {}) {
  return render(<MemoryRouter><DirectoryHarness {...props} /></MemoryRouter>);
}
function search(value) {
  const input = screen.getByRole("searchbox", { name: "搜索会议期刊" });
  fireEvent.change(input, { target: { value } });
  fireEvent.submit(input.closest("form"));
}

it("shows all four source types, real counts and an honest zero-record state", () => {
  renderDirectory();
  for (const venue of venues) expect(screen.getByRole("link", { name: `浏览 ${venue.abbr} 论文` })).toBeInTheDocument();
  expect(screen.getByText("等待回填 · 暂无已收录论文")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("5 个来源");
  expect(screen.getByRole("link", { name: "浏览 NeurIPS 论文" })).toHaveAttribute("href", "/papers?venue=NeurIPS&level=A&type=conf");
  expect(screen.getByRole("link", { name: "浏览 TOIS 论文" })).toHaveAttribute("href", "/papers?venue=TOIS&level=B&type=journal");
});

it("searches nonadjacent name fragments, case variants and typos and can clear them", () => {
  renderDirectory();
  search("MACH learn");
  expect(screen.getAllByRole("link")).toHaveLength(1);
  expect(screen.getByRole("link", { name: "浏览 ICML 论文" })).toBeInTheDocument();
  search("NUERIPS");
  expect(screen.getAllByRole("link")).toHaveLength(1);
  expect(screen.getByRole("link", { name: "浏览 NeurIPS 论文" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "清空搜索" }));
  expect(screen.getAllByRole("link")).toHaveLength(5);
});

it("combines field filters with search and resets an empty search without leaving the scope", () => {
  renderDirectory();
  fireEvent.click(screen.getByRole("button", { name: /数据库与信息检索/ }));
  expect(screen.getAllByRole("link")).toHaveLength(1);
  search("unrelatedsourcexyz");
  expect(screen.getByRole("heading", { name: "没有匹配的会议或期刊" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "重置名称与领域" }));
  expect(screen.getAllByRole("link")).toHaveLength(5);
});

it("searches the complete catalog, not only the visible preview, and supports expansion", () => {
  renderDirectory({ pageSize: 2 });
  expect(screen.getAllByRole("link")).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: /继续显示来源/ }));
  expect(screen.getAllByRole("link")).toHaveLength(4);
  search("tois");
  expect(screen.getByRole("link", { name: "浏览 TOIS 论文" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /继续显示来源/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "清空搜索" }));
  expect(screen.getAllByRole("link")).toHaveLength(2);
});

it("sorts by name and only shows topic labels supported by per-source statistics", () => {
  renderDirectory({ signatures: { NeurIPS: [{ code: "llm", paper_count: 3 }] } });
  fireEvent.change(screen.getByRole("combobox", { name: "来源排序" }), { target: { value: "name" } });
  expect(screen.getAllByRole("link")[0]).toHaveAccessibleName("浏览 COLING 论文");
  const neurips = screen.getByRole("link", { name: "浏览 NeurIPS 论文" });
  expect(within(neurips).getByText("大语言模型")).toHaveAttribute("title", "大语言模型：3 篇");
  expect(within(screen.getByRole("link", { name: "浏览 ICML 论文" })).queryByText("大语言模型")).not.toBeInTheDocument();
});
