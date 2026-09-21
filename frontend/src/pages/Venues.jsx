import { useState } from "react";
import { Link } from "react-router-dom";
import { useDashboard } from "../hooks/useResearchData.js";
import { useFilters } from "../hooks/useFilters.js";
import { number, paperHref, scopeParams } from "../lib/presentation.js";
import Icon from "../components/Icon.jsx";
import ScopeTabs from "../components/ScopeTabs.jsx";
import { MiniBars } from "../components/Charts.jsx";
import { EmptyState, ErrorState, LoadingState } from "../components/States.jsx";

export default function Venues() {
  const { filters, update } = useFilters();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("count");
  const dashboard = useDashboard(scopeParams(filters));
  const venues = (dashboard.data?.venues || []).filter((v) => `${v.abbr} ${v.name} ${v.ccf_area}`.toLowerCase().includes(search.toLowerCase())).sort((a, b) => sort === "name" ? a.abbr.localeCompare(b.abbr) : b.paper_count - a.paper_count || a.abbr.localeCompare(b.abbr));
  return <div className="venues-page page-enter"><div className="page-heading"><div><div className="eyebrow"><span className="tiny-line" />VENUE ATLAS</div><h1>找到你关注的<span>学术坐标。</span></h1><p>会议与期刊的收录概况，和通向每个研究社区的入口。</p></div><div className="page-heading-tag"><Icon name="building" size={16} />{dashboard.data?.configured_venues ?? "—"} 个配置来源</div></div>
    <ScopeTabs filters={filters} onChange={update} />
    <div className="venues-toolbar"><div className="search-input"><Icon name="search" size={19} /><input aria-label="搜索会议期刊" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="按缩写、全称或领域查找，例如 NeurIPS…" /></div><select aria-label="来源排序" value={sort} onChange={(e) => setSort(e.target.value)}><option value="count">按已收录论文数</option><option value="name">按名称 A–Z</option></select></div>
    {dashboard.isPending ? <LoadingState rows={3} /> : dashboard.error ? <ErrorState message={dashboard.error.message} onRetry={() => dashboard.refetch()} /> : venues.length ? <div className="venues-grid">{venues.map((v) => <Link key={v.abbr} to={paperHref(null, { venue: v.abbr, ...scopeParams(filters) })} className="venue-card panel"><div className="venue-card-head"><span className={`level-badge level-${v.level?.toLowerCase()}`}>CCF {v.level}</span><span>{v.type === "conf" ? "会议" : "期刊"}</span><Icon name="external" size={14} /></div><h2>{v.abbr}</h2><p className="venue-fullname">{v.name}</p><div className="venue-card-area"><Icon name="layers" size={13} />{v.ccf_area || "人工智能"}</div><div className="venue-card-data"><div><strong>{number(v.paper_count)}</strong><small>篇已收录论文</small></div><MiniBars years={v.years || []} /></div><div className="venue-card-footer"><span className={v.paper_count ? "venue-ready" : "venue-empty"}><i />{v.paper_count ? "可浏览已收录论文" : "暂未收录 · 不代表没有发表"}</span><Icon name="arrow" size={15} /></div></Link>)}</div> : <EmptyState title="没有匹配的会议或期刊" message="试试搜索缩写，或者切换 A/B 来源范围。" />}
    <div className="data-notice"><Icon name="info" size={16} /><span>此处列出当前配置的 CCF A/B 来源，不是整个推荐目录。零收录仅表示本地暂无数据，不推断会议是否举行或期刊是否发表。</span></div>
  </div>;
}
