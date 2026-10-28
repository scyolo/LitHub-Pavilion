import { useEffect, useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import Icon from "../components/Icon.jsx";
import { EmptyState, ErrorState, LoadingState } from "../components/States.jsx";
import { formatDate, number, paperHref } from "../lib/presentation.js";
import { REPORT_KINDS, filterReports, groupReports, kindLabel, loadIndustryFeed } from "../lib/industry.js";

function ReportCard({ report }) {
  return <article className="industry-report-card">
    <div className="industry-report-top"><span className={`industry-kind kind-${report.kind}`}>{kindLabel(report.kind)}</span><span className="industry-report-date">{formatDate(report.published)}</span></div>
    <h3><a href={report.url} target="_blank" rel="noopener noreferrer">{report.title}<Icon name="external" size={13} /></a></h3>
    <p className="industry-report-summary">{report.summary}</p>
    <div className="industry-report-tags">{report.tags.map(tag => <span key={tag}>{tag}</span>)}</div>
    <div className="industry-report-footer"><span>{report.arxiv_id ? `arXiv:${report.arxiv_id}` : report.kind === "journal_article" ? "期刊论文" : "官方发布"}</span><span>{report.year}</span></div>
  </article>;
}

export default function Industry() {
  const [params, setParams] = useSearchParams();
  const org = params.get("org") || "";
  const kind = Object.hasOwn(REPORT_KINDS, params.get("kind")) ? params.get("kind") : "";
  const q = params.get("q") || "";
  const setFilter = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };
  const query = useQuery({ queryKey: ["industry"], queryFn: ({ signal }) => loadIndustryFeed(signal), staleTime: 3600000, retry: 1 });
  useEffect(() => { if (query.data) performance.mark("lithub-industry-ready"); }, [query.data]);
  const data = query.data;
  const reports = data?.reports || [];
  const orgs = data?.orgs || [];
  const filtered = useMemo(() => filterReports(reports, orgs, { org, kind, q }), [data, org, kind, q]);
  const groups = useMemo(() => groupReports(filtered, orgs), [filtered, orgs]);
  const activeOrg = orgs.find(item => item.code === org);
  const years = Object.keys(data?.stats?.by_year || {});
  const coverage = years.length ? (years[0] === years[years.length - 1] ? years[0] : `${years[0]}–${years[years.length - 1]}`) : "—";
  const cardCount = data ? (data.stats.by_kind.system_card || 0) + (data.stats.by_kind.model_card || 0) : 0;
  return <div className="industry-page page-enter">
    <section className="page-heading"><div><div className="eyebrow"><span className="tiny-line" />INDUSTRY REPORTS</div><h1>从模型到系统，<span>读一手报告。</span></h1><p>DeepSeek 与国内外主要大厂的技术报告、系统卡与模型论文 · 以机构为子目录，独立于 CCF A/B 论文库。</p></div><div className="heading-actions"><Link className="button secondary small-button" to={paperHref(null, { direction: "llm" })}>浏览 LLM 论文</Link><button className="button secondary small-button" onClick={() => query.refetch()} disabled={query.isFetching}><Icon name="refresh" size={15} className={query.isFetching ? "spin" : ""} />刷新目录</button></div></section>
    {query.isPending ? <LoadingState rows={3} /> : query.error ? <ErrorState message={query.error.message} onRetry={() => query.refetch()} /> : <>
      <section className="industry-summary" aria-label="大厂技术报告概览">
        <div className="industry-summary-main"><span className="industry-summary-icon"><Icon name="sparkles" size={25} /></span><div><span className="eyebrow">CURATED INDUSTRY REPORTS</span><strong>{number(data.stats.reports)} <small>份公开报告</small></strong><p>{number(data.stats.orgs)} 家机构 · 覆盖 {coverage} 年 · 仅索引官方元数据</p></div></div>
        <div className="industry-summary-stat"><small>报告构成</small><strong>{number(data.stats.by_kind.tech_report || 0)}<span>份技术报告</span></strong><p>{number(data.stats.by_kind.paper || 0)} 篇研究论文 · {number(cardCount)} 份系统卡 / 模型卡</p></div>
        <div className="industry-summary-next"><small>最新收录</small><strong>{formatDate(data.stats.latest)}</strong><p>DeepSeek 与国内外主要大厂</p></div>
      </section>
      <div className="industry-source-note"><Icon name="info" size={16} /><p><strong>独立静态目录。</strong> 数据生成于 {formatDate(data.generated_at, true)}；只收录公开元数据与官方链接，不镜像全文，也不计入 CCF A/B 论文库统计。机构按本目录收录量排列。</p></div>
      <section className="industry-workbench panel" aria-label="筛选大厂技术报告">
        <div className="industry-toolbar"><div className="search-input"><Icon name="search" size={18} /><input aria-label="搜索大厂技术报告" value={q} onChange={event => setFilter("q", event.target.value)} placeholder="模糊搜索机构、标题、主题或年份，不区分大小写…" /></div><select aria-label="报告类型" value={kind} onChange={event => setFilter("kind", event.target.value)}><option value="">全部类型</option>{Object.entries(REPORT_KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
        <div className="industry-org-strip" role="group" aria-label="按机构筛选"><button aria-pressed={!org} className={!org ? "active" : ""} onClick={() => setFilter("org", "")}>全部机构<span>{number(data.stats.reports)}</span></button>{orgs.map(item => <button key={item.code} aria-pressed={org === item.code} className={org === item.code ? "active" : ""} onClick={() => setFilter("org", org === item.code ? "" : item.code)}>{item.name}<span>{number(item.count)}</span></button>)}</div>
      </section>
      <div className="industry-results-heading"><div><h2>{activeOrg ? activeOrg.name : "全部机构"}<span>{filtered.length}</span></h2><p>{q || kind ? "当前筛选结果 · " : ""}按机构分组，组内按发布日期倒序；技术报告未经本站同行评审。</p></div>{activeOrg && <button className="text-button" onClick={() => setFilter("org", "")}>查看全部机构</button>}</div>
      {groups.length ? <div className="industry-org-list">{groups.map(({ org: item, reports: rows }) => <section className={`industry-org-section panel ${item.code === "deepseek" ? "industry-featured" : ""}`} key={item.code} aria-labelledby={`industry-org-${item.code}`}>
        <div className="industry-org-heading"><div><div className="industry-org-title"><h2 id={`industry-org-${item.code}`}>{item.name}</h2><span>{item.name_en}</span></div><p>{item.note} · {item.country}</p></div><span className="industry-org-count">{rows.length} / {item.count} 份</span></div>
        <div className="industry-report-grid">{rows.map(report => <ReportCard key={report.id} report={report} />)}</div>
      </section>)}</div> : <EmptyState title="没有匹配的技术报告" message="可以清除机构或类型筛选，或换一个机构名、模型名、主题关键词。" />}
      <div className="industry-bottom-note"><p><strong>如何阅读：</strong>技术报告与系统卡由各机构自行发布，模型能力与安全结论请以原文及后续独立评测为准。arXiv 条目链接到官方摘要页，机构博客与代码库链接到原始发布。</p></div>
    </>}
  </div>;
}
