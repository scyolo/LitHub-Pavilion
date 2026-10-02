import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useDashboard } from "../hooks/useResearchData.js";
import { useFilters } from "../hooks/useFilters.js";
import { number, paperHref, scopeParams, topic } from "../lib/presentation.js";
import Icon from "../components/Icon.jsx";
import ScopeTabs from "../components/ScopeTabs.jsx";
import { MiniBars } from "../components/Charts.jsx";
import { EmptyState, ErrorState, LoadingState } from "../components/States.jsx";

const AREA_LABELS = {
  "计算机体系结构/并行与分布计算/存储系统": "体系结构与分布式",
  "软件工程/系统软件/程序设计语言": "软件工程与系统软件",
  "数据库/数据挖掘/内容检索": "数据库与信息检索",
};

export default function Venues() {
  const { filters, update } = useFilters();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("count");
  const [area, setArea] = useState("");
  const [visible, setVisible] = useState(24);
  const scope = scopeParams(filters);
  const dashboard = useDashboard(scope);
  const signatures = useQuery({ queryKey: ["venue-topics", scope], queryFn: ({ signal }) => api.venueTopics(scope, signal), enabled: Boolean(api.venueTopics) });
  const sourceVenues = dashboard.data?.venues || [];
  const areas = useMemo(() => {
    const values = new Map();
    for (const venue of sourceVenues) values.set(venue.ccf_area, (values.get(venue.ccf_area) || 0) + 1);
    return [...values.entries()].sort((a, b) => a[0].localeCompare(b[0], "zh-CN"));
  }, [dashboard.data]);
  const venues = useMemo(() => sourceVenues.filter(v => (!area || v.ccf_area === area)
    && `${v.abbr} ${v.name} ${v.ccf_area}`.toLowerCase().includes(search.trim().toLowerCase()))
    .sort((a, b) => sort === "name" ? a.abbr.localeCompare(b.abbr) : b.paper_count - a.paper_count || a.abbr.localeCompare(b.abbr)), [dashboard.data, area, search, sort]);
  useEffect(() => setVisible(24), [area, search, sort, filters.level, filters.type]);
  useEffect(() => { if (area && !areas.some(([value]) => value === area)) setArea(""); }, [areas, area]);
  return <div className="venues-page page-enter">
    <div className="page-heading"><div><div className="eyebrow"><span className="tiny-line" />VENUE ATLAS</div><h1>找到你关注的<span>学术坐标。</span></h1><p>只看 CCF A / B 顶会顶刊：按学科定位来源，再看每个研究社区的真实主题分布。</p></div><div className="page-heading-tag"><Icon name="building" size={16} />{dashboard.data?.configured_venues ?? "—"} 个配置来源</div></div>
    <div className="data-notice"><Icon name="info" size={16}/><span>部分会议论文以期刊形式发表，原论文不重复入库。</span><Link to="/coverage" className="text-button">查看全部来源覆盖与官网证据 →</Link></div>
    <ScopeTabs filters={filters} onChange={update} />
    {areas.length > 0 && <div className="venue-area-filters" role="group" aria-label="CCF 学科领域"><button aria-pressed={!area} className={!area ? "active" : ""} onClick={() => setArea("")}>全部领域<span>{sourceVenues.length}</span></button>{areas.map(([value, count]) => <button key={value} title={value} aria-pressed={area === value} className={area === value ? "active" : ""} onClick={() => setArea(value)}>{AREA_LABELS[value] || value}<span>{count}</span></button>)}</div>}
    <div className="venues-toolbar"><div className="search-input"><Icon name="search" size={19} /><input aria-label="搜索会议期刊" value={search} onChange={e => setSearch(e.target.value)} placeholder="按缩写、全称或领域查找，例如 CHI、NeurIPS…" /></div><select aria-label="来源排序" value={sort} onChange={e => setSort(e.target.value)}><option value="count">按已收录论文数</option><option value="name">按名称 A–Z</option></select></div>
    {dashboard.isPending ? <LoadingState rows={3} /> : dashboard.error ? <ErrorState message={dashboard.error.message} onRetry={() => dashboard.refetch()} /> : <>
      <p className="venue-result-count">{venues.length} 个匹配来源 · {venues.filter(v => v.paper_count > 0).length} 个已有论文 · 下方主题来自论文多标签统计，不是来源的唯一研究方向</p>
      {venues.length ? <><div className="venues-grid">{venues.slice(0, visible).map(v => <Link key={v.abbr} to={paperHref(null, { venue: v.abbr, ...scope })} className="venue-card panel">
        <div className="venue-card-head"><span className={`level-badge level-${v.level?.toLowerCase()}`}>CCF {v.level}</span><span>{v.type === "conf" ? "会议" : "期刊"}</span><Icon name="external" size={14} /></div>
        <h2>{v.abbr}</h2><p className="venue-fullname">{v.name}</p><div className="venue-card-area"><Icon name="layers" size={13} />{v.ccf_area || "领域待核验"}</div>
        <div className="venue-topic-tags" aria-label={`${v.abbr} 的主要研究主题`}>{(signatures.data?.items?.[v.abbr] || []).slice(0, 3).map(item => { const t = topic(item.code, dashboard.data.directions.find(d => d.code === item.code)?.name); return <span key={item.code} style={{ "--topic": t.color }} title={`${t.name}：${number(item.paper_count)} 篇`}>{t.name}</span>; })}</div>
        <div className="venue-card-data"><div><strong>{number(v.paper_count)}</strong><small>篇已收录论文</small></div><MiniBars years={v.years || []} /></div><div className="venue-card-footer"><span className={v.paper_count ? "venue-ready" : "venue-empty"}><i />{v.paper_count ? "可浏览已收录论文" : "等待回填 · 不计入论文覆盖"}</span><Icon name="arrow" size={15} /></div>
      </Link>)}</div>{visible < venues.length && <div className="venues-load-more"><button className="button secondary" onClick={() => setVisible(value => value + 24)}>继续浏览来源 <span>（已显示 {Math.min(visible, venues.length)} / {venues.length}）</span></button></div>}</> : <EmptyState title="没有匹配的会议或期刊" message="试试搜索缩写，或者切换 A/B 来源范围和学科领域。" />}
    </>}
    <div className="data-notice"><Icon name="info" size={16} /><span>仅配置 CCF 官方目录中的 A / B 类会议和期刊，不收集 C 类或目录外来源。新增来源分批回填；“来源已配置”不等于“论文已收录”，零记录也不代表该来源没有正式发表论文。</span></div>
  </div>;
}
