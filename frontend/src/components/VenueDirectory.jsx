import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { number } from "../lib/presentation.js";
import { searchVenues } from "../lib/search.js";
import Icon from "./Icon.jsx";
import SearchInput from "./SearchInput.jsx";
import VenueCard from "./VenueCard.jsx";
import { EmptyState } from "./States.jsx";

const AREA_LABELS = {
  "计算机体系结构/并行与分布计算/存储系统": "体系结构与分布式",
  "软件工程/系统软件/程序设计语言": "软件工程与系统软件",
  "数据库/数据挖掘/内容检索": "数据库与信息检索",
};
const EMPTY = [];

export default function VenueDirectory({ venues = EMPTY, directions = EMPTY, signatures = {}, scope = {}, pageSize = 24, filters, onFiltersChange }) {
  const { search = "", sort = "count", area = "" } = filters;
  const updateFilters = useCallback(changes => onFiltersChange(previous => ({ ...previous, ...changes })), [onFiltersChange]);
  const [visible, setVisible] = useState(pageSize);
  const helpId = useId();
  const areas = useMemo(() => {
    const counts = new Map();
    for (const venue of venues) {
      const value = venue.ccf_area || "领域待核验";
      counts.set(value, (counts.get(value) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0], "zh-CN"));
  }, [venues]);
  const activeArea = areas.some(([value]) => value === area) ? area : "";
  const matches = useMemo(() => searchVenues(
    venues.filter(venue => !activeArea || (venue.ccf_area || "领域待核验") === activeArea), search, sort,
  ), [venues, activeArea, search, sort]);
  useEffect(() => setVisible(pageSize), [activeArea, search, sort, scope.level, scope.type, pageSize]);
  useEffect(() => { if (area && !activeArea) updateFilters({ area: "" }); }, [area, activeArea, updateFilters]);

  return <div className="venue-directory">
    <div className="venues-toolbar">
      <SearchInput value={search} onCommit={search => updateFilters({ search })} label="搜索会议期刊" descriptionId={helpId}
        placeholder="搜索缩写、全称或领域，例如 neurips、machine learn…" />
      <select aria-label="来源排序" value={sort} onChange={event => updateFilters({ sort: event.target.value })}>
        <option value="count">按已收录论文数</option><option value="name">按名称 A–Z</option><option value="area">按 CCF 领域</option>
      </select>
    </div>
    <p className="search-help" id={helpId}><Icon name="sparkles" size={13} />模糊查询 · 不区分大小写 · 支持名称片段、多个关键词与轻微拼写错误</p>
    {areas.length > 0 && <div className="venue-area-filters" role="group" aria-label="CCF 学科领域">
      <button aria-pressed={!activeArea} className={!activeArea ? "active" : ""} onClick={() => updateFilters({ area: "" })}>全部领域<span>{venues.length}</span></button>
      {areas.map(([value, count]) => <button key={value} title={value} aria-pressed={activeArea === value}
        className={activeArea === value ? "active" : ""} onClick={() => updateFilters({ area: value })}>{AREA_LABELS[value] || value}<span>{count}</span></button>)}
    </div>}
    <div className="venue-directory-status">
      <p className="venue-result-count" role="status" aria-live="polite"><strong>{number(matches.length)}</strong> 个来源{search ? "匹配查询" : "可浏览"}<span> · {number(matches.filter(venue => venue.paper_count > 0).length)} 个已有论文</span></p>
      <span className="venue-directory-note">{search ? "精确命中优先，近似匹配随后" : "收录量排序，不代表学术排名"}</span>
    </div>
    {matches.length ? <>
      <div className="venues-grid">{matches.slice(0, visible).map(venue => <VenueCard key={venue.abbr} venue={venue}
        topics={signatures[venue.abbr] || EMPTY} directions={directions} />)}</div>
      {(visible < matches.length || visible > pageSize) && <div className="venues-load-more">
        {visible < matches.length && <button className="button secondary" onClick={() => setVisible(value => value + pageSize)}>
          继续显示来源 <Icon name="chevronDown" size={14} /><span>已显示 {Math.min(visible, matches.length)} / {number(matches.length)}</span>
        </button>}
        {visible > pageSize && <button className="text-button" onClick={() => setVisible(pageSize)}>收起列表</button>}
      </div>}
    </> : <EmptyState title="没有匹配的会议或期刊" message="试试更短的名称片段，或切换 CCF 类别和学科领域。"
      action={(search || activeArea) && <button className="button secondary" onClick={() => updateFilters({ search: "", area: "" })}>重置名称与领域</button>} />}
  </div>;
}
