import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { useDashboard } from "../hooks/useResearchData.js";
import { useFilters } from "../hooks/useFilters.js";
import { TOPICS, filteredParams, formatDate, number, paperHref, percent, topic } from "../lib/presentation.js";
import { APP_NAME, APP_DESCRIPTION } from "../lib/brand.js";
import Icon from "../components/Icon.jsx";
import ScopeTabs from "../components/ScopeTabs.jsx";
import { AnnualChart, LinkCoverage, TopicChart } from "../components/Charts.jsx";
import PaperCard from "../components/PaperCard.jsx";
import { EmptyState, ErrorState, LoadingState, SectionTitle } from "../components/States.jsx";

export default function Home() {
  const { filters, update } = useFilters();
  const navigate = useNavigate();
  const scope = filteredParams({ level: filters.level, type: filters.type });
  const dashboard = useDashboard(scope);
  const data = dashboard.data;
  const latest = useQuery({ queryKey: ["papers", "latest", scope], queryFn: ({ signal }) => api.latest(scope, signal), refetchInterval: api.isSnapshot ? false : 30000 });
  const openPapers = (extra) => navigate(paperHref(null, { ...scope, ...extra }));

  return <div className="dashboard-page page-enter">
    <section className="page-heading dashboard-heading">
      <div><div className="eyebrow"><span className="tiny-line" /> RESEARCH OVERVIEW</div><h1>{APP_NAME}</h1><p>{APP_DESCRIPTION}</p></div>
      <div className="heading-actions"><span className="muted small">{api.isSnapshot ? "公开快照" : "本地数据"} · {data ? formatDate(data.generated_at, true) : "读取中"}</span><button className="button secondary small-button" onClick={async () => { if (api.isSnapshot) { await api.refreshSnapshot().catch(() => {}); } else { dashboard.refetch(); latest.refetch(); } }} disabled={dashboard.isFetching} aria-label="刷新总览数据"><Icon name="refresh" size={15} className={dashboard.isFetching ? "spin" : ""} />刷新</button></div>
    </section>
    <div className="scope-row"><ScopeTabs filters={filters} onChange={update} /><span className="scope-hint"><Icon name="shield" size={14} />仅当前配置的 A / B 清单</span></div>
    {dashboard.isPending ? <LoadingState rows={3} /> : dashboard.error ? <ErrorState message={dashboard.error.message} onRetry={() => dashboard.refetch()} /> : <>
      <section className="metrics-grid" aria-label="论文库概览">
        <Metric icon="book" label="已收录论文" value={number(data.total)} note={api.isSnapshot ? "当前筛选范围的快照记录" : "当前筛选范围的本地记录"} color="blue" />
        <Metric icon="building" label="已配置会议 / 期刊" value={number(data.configured_venues)} note={`${data.venues_with_papers} 个已有论文记录`} color="mint" />
        <Metric icon="layers" label="研究方向" value={number(data.directions.length)} note="一篇论文可属于多个方向" color="violet" />
        <Metric icon="link" label="开放链接覆盖" value={percent(data.with_oa_link, data.total)} note={`${number(data.with_oa_link)} 篇有开放版本链接`} color="amber" />
      </section>
      <div className="dashboard-charts"><AnnualChart data={data.annual} onSelect={(year) => openPapers({ year })} /><TopicChart data={data.directions} onSelect={(direction) => openPapers({ direction })} /></div>
      <section className="topics-section">
        <SectionTitle icon="sparkles" title="从感兴趣的方向开始" note="你的核心方向与相邻领域，始终限定在 A / B 类范围内"><span className="section-caption">点击探索论文 <Icon name="arrow" size={14} /></span></SectionTitle>
        <div className="topic-tiles">{[...data.directions].sort((a, b) => Object.keys(TOPICS).indexOf(a.code) - Object.keys(TOPICS).indexOf(b.code)).map((d) => {
          const t = topic(d.code, d.name);
          return <button key={d.code} className="topic-tile" style={{ "--topic": t.color }} onClick={() => openPapers({ direction: d.code })}>
            <span className="topic-tile-icon"><Icon name={t.icon} size={20} /></span><span className="topic-tile-copy"><strong>{d.name}</strong><small>{t.short}</small></span><span className="topic-tile-count">{number(d.paper_count)}<Icon name="chevron" size={13} /></span>
          </button>;
        })}</div>
      </section>
      <div className="dashboard-bottom">
        <section className="recent-section"><SectionTitle icon="clock" title="最新发表" note="按上游发布日期倒序；缺少日期时按归属年份"><Link className="text-link" to={paperHref(null, scope)}>全部论文<Icon name="arrow" size={14} /></Link></SectionTitle>
          {latest.isPending ? <LoadingState rows={3} /> : latest.error ? <ErrorState message={latest.error.message} onRetry={() => latest.refetch()} /> : latest.data?.items.length ? <div className="paper-stack">{latest.data.items.map((p) => <PaperCard key={p.id} paper={p} compactMode />)}</div> : <EmptyState title="这个范围还没有论文" message="数据可能尚未回填，可以在采集管理中查看进度。" />}
        </section>
        <aside className="insights-sidebar">
          <section className="panel venue-ranking"><SectionTitle icon="building" title="收录量较多的来源" note={api.isSnapshot ? "快照论文数 · 非学术质量排名" : "本地论文数 · 非学术质量排名"} /><ol>{[...data.venues].filter((v) => v.paper_count).sort((a, b) => b.paper_count - a.paper_count).slice(0, 5).map((v, index) => <li key={v.abbr}><button onClick={() => openPapers({ venue: v.abbr })}><span className="rank numeric">{String(index + 1).padStart(2, "0")}</span><span className="ranking-name">{v.abbr}<small>{v.type === "journal" ? "期刊" : "会议"} · CCF {v.level}</small></span><strong className="numeric">{number(v.paper_count)}</strong><Icon name="chevron" size={13} /></button></li>)}</ol><Link to="/venues" className="text-link">浏览会议与期刊<Icon name="arrow" size={14} /></Link></section>
          <section className="panel"><LinkCoverage total={data.total} oa={data.with_oa_link} onSelect={(access) => openPapers({ access })} /></section>
          <section className="sync-panel"><div className="sync-icon"><Icon name="radar" size={23} /></div><h3>{api.isSnapshot ? "按需更新，随时阅读" : "每周同步，轻量追踪"}</h3><p>{api.isSnapshot ? "Docker 负责采集和发布。网站读取最新完整快照，本地后端关闭后仍可筛选、搜索并访问原文。" : "只保留论文元数据与原始链接，不下载 PDF。图表随本地数据自动刷新。"}</p><div className="sync-detail"><span>最近一次采集</span><strong>{data.last_crawl ? formatDate(data.last_crawl.started_at) : "尚无记录"}</strong></div><Link to="/admin" className="text-link">查看同步详情<Icon name="arrow" size={14} /></Link></section>
        </aside>
      </div>
      <div className="data-notice"><Icon name="info" size={16} /><span>统计仅覆盖已收录数据。当前年份、来源缺口与自动方向标签均可能不完整；{number(data.total - data.confirmed_count)} 篇发表归属尚待核验。目录级别以已配置 CCF 清单为准。</span></div>
    </>}
  </div>;
}

function Metric({ icon, label, value, note, color }) {
  return <div className={`metric-card metric-${color}`}><div className="metric-top"><span>{label}</span><span className="metric-icon"><Icon name={icon} size={18} /></span></div><strong className="metric-value numeric">{value}</strong><p>{note}</p></div>;
}
