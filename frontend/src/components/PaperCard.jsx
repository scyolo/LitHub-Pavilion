import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { compact, paperHref, paperLinks, topic } from "../lib/presentation.js";
import Icon from "./Icon.jsx";

export default function PaperCard({ paper, compactMode = false }) {
  const [expanded, setExpanded] = useState(false);
  const location = useLocation();
  const links = paperLinks(paper);
  const authors = paper.authors_preview?.length ? paper.authors_preview.join(" · ") : paper.first_author;
  return (
    <article className={`paper-card ${compactMode ? "compact" : ""}`}>
      <div className="paper-card-body">
        <div className="paper-meta">
          <Link to={paperHref(null, { venue: paper.venue })} className="venue-label">{paper.venue}</Link>
          <span className={`level-badge level-${paper.level?.toLowerCase()}`}>CCF {paper.level}</span>
          <span>{paper.venue_type === "journal" ? "期刊" : "会议"}</span><span className="meta-dot">·</span><span className="numeric">{paper.year}</span>
          {links.oa && <span className="oa-badge"><span />开放获取</span>}
          {!paper.venue_confirmed && <span className="unverified" title="现有元数据未完成发表归属核验，不代表正式录用">归属待核验</span>}
        </div>
        <Link className="paper-title" to={`/papers/${paper.id}`} state={{ from: location.pathname + location.search }}>{paper.title}</Link>
        <div className="paper-authors">{authors || "作者信息暂缺"}{paper.authors_count > 3 ? ` 等 ${paper.authors_count} 位作者` : ""}</div>
        {!compactMode && paper.abstract_preview && <p className={`paper-abstract ${expanded ? "expanded" : ""}`}>{paper.abstract_preview}</p>}
        <div className="paper-card-bottom">
          <div className="topic-tags">{(paper.directions || []).map((code) => {
            const t = topic(code);
            return <Link key={code} to={paperHref(null, { direction: code })} className="topic-tag" style={{ "--topic": t.color }}>{t.name}</Link>;
          })}</div>
          <div className="paper-actions">
            <span className="citation-count" title="外部数据源记录的引用数，可能存在收录延迟"><Icon name="chart" size={14} />{compact(paper.citation_count)}<span>引用</span></span>
            {!compactMode && paper.abstract_preview && <button className="text-button abstract-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "收起摘要" : "摘要"}<Icon name="chevronDown" size={12} /></button>}
            {links.official && <a href={links.official} target="_blank" rel="noopener noreferrer" className="paper-external">官方链接<Icon name="external" size={13} /></a>}
            {!links.official && links.oa && <a href={links.oa} target="_blank" rel="noopener noreferrer" className="paper-external">开放版本<Icon name="external" size={13} /></a>}
          </div>
        </div>
      </div>
    </article>
  );
}
