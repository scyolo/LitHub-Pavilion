import { Link } from "react-router-dom";
import { number, paperHref, topic } from "../lib/presentation.js";
import { MiniBars } from "./Charts.jsx";
import Icon from "./Icon.jsx";

export default function VenueCard({ venue, topics = [], directions = [] }) {
  const years = venue.years || [];
  return <Link to={paperHref(null, { venue: venue.abbr, level: venue.level, type: venue.type })}
    className="venue-card panel" aria-label={`浏览 ${venue.abbr} 论文`}>
    <div className="venue-card-head">
      <span className={`level-badge level-${venue.level?.toLowerCase()}`}>CCF {venue.level}</span>
      <span className="venue-kind"><Icon name={venue.type === "conf" ? "building" : "book"} size={12} />{venue.type === "conf" ? "会议" : "期刊"}</span>
      <Icon name="arrow" size={15} />
    </div>
    <h3>{venue.abbr}</h3>
    <p className="venue-fullname" title={venue.name}>{venue.name}</p>
    <div className="venue-card-area"><Icon name="layers" size={13} /><span>{venue.ccf_area || "领域待核验"}</span></div>
    <div className="venue-topic-tags" aria-label={`${venue.abbr} 的主要研究主题`}>
      {topics.slice(0, 3).map(item => {
        const label = topic(item.code, directions.find(direction => direction.code === item.code)?.name);
        return <span key={item.code} style={{ "--topic": label.color }} title={`${label.name}：${number(item.paper_count)} 篇`}>{label.name}</span>;
      })}
    </div>
    <div className="venue-card-data">
      <div><strong>{number(venue.paper_count)}</strong><small>篇已收录论文</small></div>
      {years.length > 0 && <div className="venue-year-trend" role="img" aria-label={`年份分布：${years.map(year => `${year.year} 年 ${number(year.count)} 篇`).join("，")}`}>
        <MiniBars years={years} /><small>{years[0].year}{years.length > 1 ? `—${years.at(-1).year}` : ""}</small>
      </div>}
    </div>
    <div className="venue-card-footer">
      <span className={venue.paper_count ? "venue-ready" : "venue-empty"}><i />{venue.paper_count ? "浏览已收录论文" : "等待回填 · 暂无已收录论文"}</span>
      <Icon name="chevron" size={14} />
    </div>
  </Link>;
}
