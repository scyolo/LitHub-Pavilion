import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useParams } from "react-router-dom";
import { api } from "../api.js";
import { formatDate, number, paperHref, paperLinks, topic } from "../lib/presentation.js";
import Icon from "../components/Icon.jsx";
import { ErrorState, LoadingState } from "../components/States.jsx";

export default function PaperDetail() {
  const { id } = useParams();
  const location = useLocation();
  const [copied, setCopied] = useState(false);
  const query = useQuery({ queryKey: ["paper", id], queryFn: ({ signal }) => api.paper(id, signal) });
  const paper = query.data;
  const candidateFrom = location.state?.from;
  const from = typeof candidateFrom === "string" && /^\/papers(?:\?|$)/.test(candidateFrom) && !candidateFrom.includes("\\") ? candidateFrom : "/papers";
  if (query.isPending) return <LoadingState rows={3} />;
  if (query.error) return <ErrorState message={query.error.message} onRetry={() => query.refetch()} />;
  if (!paper) return <ErrorState />;
  const links = paperLinks(paper);
  const venue = paper.venue || {};

  async function copyCitation() {
    const text = `${(paper.authors || []).map((a) => a.name).join(", ")}. ${paper.title}. ${venue.abbr}, ${paper.year}.${paper.doi ? ` https://doi.org/${paper.doi}` : ""}`;
    try { await navigator.clipboard.writeText(text); setCopied(true); } catch { setCopied(false); }
  }

  return <article className="detail-page page-enter">
    <Link to={from} className="back-link"><Icon name="back" size={16} />返回论文探索</Link>
    <div className="detail-heading"><div className="paper-meta"><Link className="venue-label" to={paperHref(null, { venue: venue.abbr })}>{venue.abbr}</Link><span className={`level-badge level-${venue.level?.toLowerCase()}`}>CCF {venue.level}</span><span>{venue.type === "journal" ? "期刊" : "会议"} · {paper.year}</span>{links.oa && <span className="oa-badge"><span />有开放版本</span>}</div><h1>{paper.title}</h1><p className="detail-authors">{(paper.authors || []).map((a) => a.name).join("  ·  ") || "作者信息暂缺"}</p><div className="detail-topics">{(paper.directions || []).map((d) => <Link key={d.code} className="topic-tag" style={{ "--topic": topic(d.code).color }} to={paperHref(null, { direction: d.code })}>{d.name}<small>{d.source === "manual" ? " · 人工" : ""}</small></Link>)}</div></div>
    <div className="detail-layout"><div className="detail-main"><section className="panel abstract-panel"><h2><Icon name="text" size={19} />论文摘要 <span>ABSTRACT</span></h2><p className={paper.abstract ? "abstract-text" : "muted"}>{paper.abstract || "上游数据源暂未提供摘要。你可以通过右侧官方链接阅读原文。"}</p></section>{paper.note && <section className="panel"><h2>研究备注</h2><p className="abstract-text">{paper.note}</p></section>}
      <section className="panel provenance-panel"><h2><Icon name="shield" size={18} />关于这条记录</h2><p>{paper.venue_confirmed ? "采集记录已与配置的 DBLP 来源对应。正式发表信息仍以会议 / 期刊官方网站为准。" : "这篇论文的发表归属尚待核验。自动关联到配置来源不等于已经确认正式录用，请核对官方页面。"}</p><p>方向标签基于标题与摘要自动匹配；引用数来自外部索引，不是实时学术评价。预印本日期与正式发表年份可能不同。</p></section></div>
      <aside className="detail-aside"><section className="panel read-panel"><div className="read-panel-title"><span className="read-icon"><Icon name="link" size={24} /></span><div><h2>阅读原文</h2><p>直达来源，不在本地存档</p></div></div>{links.official ? <a className="button primary full-width" href={links.official} target="_blank" rel="noopener noreferrer"><Icon name="external" size={16} />访问官方页面<Icon name="arrow" size={16} /></a> : <p className="muted small">暂无可用官方链接。</p>}{links.oa && links.oa !== links.official && <a className="button secondary full-width" href={links.oa} target="_blank" rel="noopener noreferrer"><Icon name="book" size={16} />阅读开放版本<Icon name="external" size={14} /></a>}{!links.oa && <p className="read-note">暂未索引到开放版本；官方链接可能需要出版方权限。</p>}<div className="read-note"><Icon name="info" size={14} />由新窗口访问原站，不下载 PDF。</div></section>
        <section className="panel metadata-panel"><h2>文献信息</h2><dl><Metadata label="来源" value={venue.name || venue.abbr} /><Metadata label="目录级别" value={`CCF ${venue.level} · ${venue.type === "journal" ? "期刊" : "会议"}`} /><Metadata label="论文归属年" value={paper.year} /><Metadata label="引用数" value={number(paper.citation_count)} /><Metadata label="发表归属" value={paper.venue_confirmed ? "已关联来源" : "待核验"} /><Metadata label="上游发布日期" value={paper.publication_date ? formatDate(paper.publication_date) : "未提供"} /><Metadata label="入库时间" value={formatDate(paper.created_at)} />{paper.doi && <Metadata label="DOI" value={paper.doi} />}{paper.arxiv_id && <Metadata label="arXiv" value={paper.arxiv_id} />}</dl><button className="button secondary full-width" onClick={copyCitation}><Icon name={copied ? "check" : "copy"} size={15} />{copied ? "引用文本已复制" : "复制引用文本"}</button><span className="sr-only" role="status">{copied ? "引用文本已复制" : ""}</span></section>
      </aside></div>
  </article>;
}

function Metadata({ label, value }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
