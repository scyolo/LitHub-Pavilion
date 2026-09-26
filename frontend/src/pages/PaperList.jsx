import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api.js";
import { useFilters } from "../hooks/useFilters.js";
import { useDashboard } from "../hooks/useResearchData.js";
import { filteredParams, number, scopeParams, topic } from "../lib/presentation.js";
import Icon from "../components/Icon.jsx";
import PaperCard from "../components/PaperCard.jsx";
import ScopeTabs from "../components/ScopeTabs.jsx";
import SearchInput from "../components/SearchInput.jsx";
import { EmptyState, ErrorState, LoadingState } from "../components/States.jsx";

export default function PaperList() {
  const { filters, update, toggleDirection, clear } = useFilters();
  const [compactMode, setCompactMode] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [venueSearch, setVenueSearch] = useState("");
  const contextQuery = useDashboard(scopeParams(filters));
  const context = contextQuery.data;
  const isSearch = Boolean(filters.q.trim());
  const requestParams = filteredParams({ ...filters, sort: !isSearch && filters.sort === "relevance" ? "publication_desc" : filters.sort });
  const result = useQuery({
    queryKey: ["papers", requestParams],
    queryFn: ({ signal }) => isSearch ? api.search(requestParams, signal) : api.papers(requestParams, signal),
    placeholderData: keepPreviousData,
    refetchInterval: api.isSnapshot ? false : 30000,
    refetchIntervalInBackground: false,
    retry: (count, error) => error.status >= 400 && error.status < 500 ? false : count < 1,
  });
  const data = result.data;
  const pages = Math.max(1, Math.ceil((data?.total || 0) / (data?.size || filters.size)));
  const selectedDirections = filters.direction.split(",").filter(Boolean);
  const directions = context?.directions || [];
  const venues = (context?.venues || []).filter((v) => `${v.abbr} ${v.name}`.toLowerCase().includes(venueSearch.toLowerCase()));
  const active = [
    ...selectedDirections.map((code) => ({ label: topic(code, directions.find((d) => d.code === code)?.name).name, remove: () => toggleDirection(code) })),
    ...(filters.venue ? [{ label: filters.venue, remove: () => update({ venue: "" }) }] : []),
    ...(filters.year ? [{ label: `${filters.year} 年`, remove: () => update({ year: "" }) }] : []),
    ...(filters.access ? [{ label: filters.access === "oa" ? "有开放版本" : "仅官方链接", remove: () => update({ access: "" }) }] : []),
  ];

  return <div className="explore-page page-enter">
    <div className="page-heading"><div><div className="eyebrow"><span className="tiny-line" />PAPER EXPLORER</div><h1>让下一篇好论文，<span>被你发现。</span></h1><p>按方向深入，按来源追踪。所有论文都保留通往原文的链接。</p></div><span className="page-heading-tag"><Icon name="book" size={15} />CCF A / B 论文库</span></div>
    <ScopeTabs filters={filters} onChange={update} />
    <div className="explorer-searchbar"><SearchInput value={filters.q} onCommit={(q) => update({ q })} label="搜索论文" placeholder="搜索英文标题、摘要关键词，例如 speculative decoding…" /><button className="button secondary filter-toggle" onClick={() => setFiltersOpen(!filtersOpen)} aria-expanded={filtersOpen}><Icon name="sliders" size={17} />筛选{active.length > 0 ? ` · ${active.length}` : ""}</button></div>
    {contextQuery.error && <ErrorState message="筛选选项暂时无法加载，已显示的论文仍可浏览。" onRetry={() => contextQuery.refetch()} />}
    <div className="explorer-layout">
      <aside className={`filters-panel panel ${filtersOpen ? "expanded" : ""}`} aria-label="论文筛选器">
        <div className="filter-panel-heading"><h2><Icon name="sliders" size={16} />筛选条件</h2><button className="text-button" onClick={clear}>重置</button></div>
        <fieldset className="filter-group"><legend>研究方向 <span>可多选</span></legend><div className="filter-options">{directions.map((d) => {
          const t = topic(d.code, d.name);
          return <label className="filter-checkbox" key={d.code}><input type="checkbox" checked={selectedDirections.includes(d.code)} onChange={() => toggleDirection(d.code)} /><span className="topic-dot" style={{ background: t.color }} /><span>{d.name}</span><small>{number(d.paper_count)}</small></label>;
        })}</div><p className="filter-explanation">同维度多选取并集，不同维度取交集。</p></fieldset>
        <div className="filter-group"><label htmlFor="year-filter">论文归属年份</label><select id="year-filter" value={filters.year} onChange={(e) => update({ year: e.target.value })}><option value="">全部年份</option>{[...(context?.annual || [])].reverse().map((d) => <option key={d.year} value={d.year}>{d.year} · {number(d.total)} 篇</option>)}</select></div>
        <div className="filter-group"><label htmlFor="venue-search">会议 / 期刊</label><div className="small-search"><Icon name="search" size={14} /><input id="venue-search" value={venueSearch} onChange={(e) => setVenueSearch(e.target.value)} placeholder="按名称查找来源" /></div><div className="venue-filter-options"><button className={!filters.venue ? "selected" : ""} onClick={() => update({ venue: "" })}>全部来源<span>{context?.configured_venues ?? "—"}</span></button>{venues.map((v) => <button key={v.abbr} title={v.name} className={filters.venue === v.abbr ? "selected" : ""} onClick={() => update({ venue: v.abbr })}>{v.abbr}<span>{number(v.paper_count)}</span></button>)}{venues.length === 0 && <p className="muted small">没有匹配的来源</p>}</div></div>
        <fieldset className="filter-group"><legend>全文访问</legend>{[{ value: "", label: "全部论文" }, { value: "oa", label: "有开放版本链接" }, { value: "official", label: "仅官方链接" }].map((item) => <label key={item.value} className="filter-radio"><input type="radio" name="access" value={item.value} checked={filters.access === item.value} onChange={() => update({ access: item.value })} />{item.label}</label>)}</fieldset>
        <div className="filter-note"><Icon name="link" size={15} /><p>直接跳转原始来源<br />本站不下载 PDF</p></div>
      </aside>
      <section className="explorer-results" aria-label="论文结果" aria-busy={result.isFetching}>
        {active.length > 0 && <div className="active-filters">{active.map((item) => <button key={item.label} onClick={item.remove} aria-label={`移除筛选：${item.label}`}>{item.label}<Icon name="close" size={12} /></button>)}</div>}
        <div className="results-toolbar"><div><strong>{result.error ? "查询未完成" : result.isPending ? "正在查找论文…" : `${number(data?.total)} 篇论文`}</strong><span>{isSearch ? `匹配 “${filters.q}”` : "探索已收录研究"}</span>{result.isFetching && !result.isPending && <Icon name="refresh" className="spin" size={13} />}</div><div className="results-options"><label className="sr-only" htmlFor="sort-papers">论文排序</label><select id="sort-papers" value={requestParams.sort} onChange={(e) => update({ sort: e.target.value })}>{isSearch && <option value="relevance">相关性优先</option>}<option value="publication_desc">发表时间从新到旧</option><option value="created_desc">最近收录</option><option value="year_desc">年份从新到旧</option><option value="citation_desc">引用数优先</option></select><div className="view-switch" role="group" aria-label="列表显示密度"><button aria-label="舒适视图" aria-pressed={!compactMode} className={!compactMode ? "active" : ""} onClick={() => setCompactMode(false)}><Icon name="grid" size={16} /></button><button aria-label="紧凑视图" aria-pressed={compactMode} className={compactMode ? "active" : ""} onClick={() => setCompactMode(true)}><Icon name="list" size={17} /></button></div></div></div>
        {result.error ? <ErrorState message={result.error.message} onRetry={() => result.refetch()} /> : result.isPending ? <LoadingState rows={4} /> : data?.items.length ? <div className={`paper-stack ${result.isPlaceholderData ? "refreshing" : ""}`}>{data.items.map((p) => <PaperCard key={p.id} paper={p} compactMode={compactMode} />)}</div> : <EmptyState action={<button className="button secondary" onClick={clear}>清除所有筛选</button>} />}
        {!result.error && data && <nav className="pagination" aria-label="论文分页"><span>第 {filters.page} / {number(pages)} 页 · 共 {number(data.total)} 篇</span><div><label className="sr-only" htmlFor="page-size">每页条数</label><select id="page-size" value={filters.size} onChange={(e) => update({ size: e.target.value })}><option value="10">10 条 / 页</option><option value="20">20 条 / 页</option><option value="50">50 条 / 页</option></select><button className="icon-button" aria-label="上一页" disabled={filters.page <= 1 || result.isPlaceholderData} onClick={() => update({ page: filters.page - 1 }, { resetPage: false })}><Icon name="back" size={17} /></button><span className="current-page">{filters.page}</span><button className="icon-button" aria-label="下一页" disabled={filters.page >= pages || result.isPlaceholderData} onClick={() => update({ page: filters.page + 1 }, { resetPage: false })}><Icon name="arrow" size={17} /></button></div></nav>}
        <p className="results-note"><Icon name="info" size={14} />缺少完整发布日期时按归属年份排序，同年仅有年份的记录排在具体日期之后。支持英文检索；方向标签为规则归类，发表归属待核验的记录会单独提示。</p>
      </section>
    </div>
  </div>;
}

