import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import { EmptyState, ErrorState, LoadingState } from "../components/States.jsx";
import { formatDate, number, paperHref } from "../lib/presentation.js";
import { adjacentMonth, calendarCells, countdown, dateKey, deadlineStatus, filterDeadlines, formatDeadline, loadDeadlineFeed, toICS } from "../lib/deadlines.js";

const DAY = 86400000;
const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];
const STATUS = [{ id: "upcoming", label: "即将截止" }, { id: "all", label: "全部轮次" }, { id: "past", label: "已截止" }, { id: "tba", label: "待公布" }];

function DeadlineCard({ event, now, timezone }) {
  const status = deadlineStatus(event, now);
  const urgent = status === "upcoming" && Date.parse(event.deadline_utc) - now <= 7 * DAY;
  const abstractClosed = status === "upcoming" && event.abstract_deadline_utc && Date.parse(event.abstract_deadline_utc) <= now;
  return <article className={`deadline-card ${urgent ? "deadline-urgent" : ""} ${status === "past" ? "deadline-past" : ""}`}>
    <div className="deadline-card-top"><span className={`level-badge level-${event.level.toLowerCase()}`}>CCF {event.level}</span><span className="deadline-area">{event.area}</span><span className={`deadline-countdown ${urgent ? "urgent" : ""}`}><Icon name="clock" size={13} />{status === "upcoming" ? "还剩 " : ""}{countdown(event, now)}</span></div>
    <div className="deadline-card-body"><div className="deadline-identity"><h3>{event.venue} <span>{event.year}</span></h3><p>{event.venue_name}</p><span className="deadline-round">{event.round}</span></div><div className="deadline-date"><small>全文截稿 · {timezone === "Asia/Shanghai" ? "北京时间" : "UTC"}</small><strong>{formatDeadline(event.deadline_utc, timezone)}</strong><span>原时区 {event.timezone || "未提供"}{event.deadline ? ` · ${event.deadline}` : ""}</span></div></div>
    <div className={`deadline-abstract ${abstractClosed ? "abstract-closed" : ""}`}><Icon name="info" size={14} />{event.abstract_deadline_utc ? <span>摘要截止：{formatDeadline(event.abstract_deadline_utc, timezone)}{abstractClosed ? " · 已截止，新投稿请先确认资格" : ""}</span> : <span>未提供摘要截止时间，请确认官网是否需提前注册。</span>}</div>
    {(event.place || event.conference_dates) && <div className="deadline-location"><span>{event.place}</span><span>{event.conference_dates}</span></div>}
    <div className="deadline-card-footer"><Link className="text-link" to={paperHref(null, { venue: event.venue })}>浏览往届论文 <Icon name="arrow" size={13} /></Link><div>{event.source_url && <a href={event.source_url} target="_blank" rel="noopener noreferrer">数据来源</a>}{event.link && <a className="deadline-official" href={event.link} target="_blank" rel="noopener noreferrer">会议官网 <Icon name="external" size={13} /></a>}</div></div>
  </article>;
}

export default function Deadlines() {
  const query = useQuery({ queryKey: ["deadlines"], queryFn: ({ signal }) => loadDeadlineFeed(signal), staleTime: 3600000, retry: 1 });
  const [now, setNow] = useState(Date.now);
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [level, setLevel] = useState("");
  const [area, setArea] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("upcoming");
  const [view, setView] = useState("calendar");
  const [month, setMonth] = useState(() => dateKey(Date.now(), "Asia/Shanghai").slice(0, 7));
  const [selectedDate, setSelectedDate] = useState(null);
  const [exported, setExported] = useState(false);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 30000); return () => clearInterval(timer); }, []);
  useEffect(() => { if (query.data) performance.mark("lithub-calendar-ready"); }, [query.data]);
  const data = query.data;
  const events = data?.events || [];
  const areas = useMemo(() => [...new Set(events.map(e => e.area))].sort((a, b) => a.localeCompare(b, "zh-CN")), [data]);
  const filtered = useMemo(() => filterDeadlines(events, { level, area, q: search, status }, now), [data, level, area, search, status, now]);
  const byDate = useMemo(() => {
    const result = new Map();
    for (const event of filtered) {
      const key = dateKey(event.deadline_utc, timezone);
      if (key) result.set(key, [...(result.get(key) || []), event]);
    }
    return result;
  }, [filtered, timezone]);
  const cells = useMemo(() => calendarCells(month), [month]);
  const monthEvents = filtered.filter(e => dateKey(e.deadline_utc, timezone).startsWith(month));
  const displayed = view === "list" || status === "tba" ? filtered : selectedDate ? byDate.get(selectedDate) || [] : monthEvents;
  const upcoming = events.filter(e => deadlineStatus(e, now) === "upcoming");
  const soon = upcoming.filter(e => Date.parse(e.deadline_utc) - now <= 30 * DAY);
  const next = upcoming[0];
  const stale = data && now - Date.parse(data.generated_at) > 7 * DAY;
  const activeDate = dateKey(now, timezone);
  const updateMonth = value => { setMonth(value); setSelectedDate(null); };
  function exportCalendar() {
    const selected = (view === "calendar" && status !== "tba" ? displayed : filtered).filter(e => e.deadline_utc);
    const url = URL.createObjectURL(new Blob([toICS(selected, now)], { type: "text/calendar;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `ccf-deadlines-${month}.ics`; document.body.appendChild(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000); setExported(true);
  }
  return <div className="deadlines-page page-enter">
    <section className="page-heading"><div><div className="eyebrow"><span className="tiny-line" />SUBMISSION PLANNER</div><h1>让下一篇论文，<span>如期抵达。</span></h1><p>CCF A / B 会议截稿日历 · 分清时区、摘要与多轮投稿，不错过重要节点。</p></div><div className="heading-actions"><button className="button secondary small-button" onClick={() => query.refetch()} disabled={query.isFetching}><Icon name="refresh" size={15} className={query.isFetching ? "spin" : ""} />更新日历</button></div></section>
    {query.isPending ? <LoadingState rows={3} /> : query.error ? <ErrorState message={query.error.message} onRetry={() => query.refetch()} /> : <>
      <section className="deadline-summary" aria-label="截稿日历概览">
        <div className="deadline-summary-main"><span className="deadline-summary-icon"><Icon name="calendar" size={25} /></span><div><span className="eyebrow">NEXT 30 DAYS</span><strong>{number(soon.length)} <small>个截稿节点</small></strong><p>{new Set(soon.map(e => e.venue)).size} 个会议 · 每个投稿轮次独立展示</p></div></div>
        <div className="deadline-summary-stat"><small>未来已公布</small><strong>{upcoming.length}<span>轮次</span></strong><p>A 类 {upcoming.filter(e => e.level === "A").length} · B 类 {upcoming.filter(e => e.level === "B").length}</p></div>
        <div className="deadline-summary-next"><small>最近一个节点</small>{next ? <><strong>{next.venue} <span>{next.year}</span></strong><p>{formatDeadline(next.deadline_utc, timezone)} · {countdown(next, now)}</p></> : <p>暂未收录未来截稿时间</p>}</div>
      </section>
      <div className={`deadline-source-note ${stale ? "is-stale" : ""}`}><Icon name="info" size={16} /><p><strong>{stale ? "数据已超过 7 天未同步。" : "日历为独立静态快照。"}</strong> 数据同步于 {formatDate(data.generated_at, true)}，覆盖 {data.coverage.matched_conferences} / {data.coverage.configured_conferences} 个配置会议的当年及未来届次；社区汇总，<strong>投稿前请以官网为准</strong>。刷新读取最新已发布文件，不实时抓取会议官网。</p></div>
      <section className="deadline-workbench panel" aria-label="筛选截稿日期">
        <div className="deadline-toolbar"><div className="deadline-levels" role="group" aria-label="会议级别">{[["", "全部 A / B"], ["A", "A 类会议"], ["B", "B 类会议"]].map(([value, label]) => <button key={value} aria-pressed={level === value} className={level === value ? "active" : ""} onClick={() => { setLevel(value); setSelectedDate(null); }}>{label}</button>)}</div><div className="deadline-view-switch" role="group" aria-label="日历视图"><button aria-pressed={view === "calendar"} onClick={() => { setView("calendar"); setSelectedDate(null); }} className={view === "calendar" ? "active" : ""}><Icon name="calendar" size={15} />月历</button><button aria-pressed={view === "list"} onClick={() => { setView("list"); setSelectedDate(null); }} className={view === "list" ? "active" : ""}><Icon name="text" size={15} />列表</button></div></div>
        <div className="deadline-filter-row"><div className="search-input"><Icon name="search" size={18} /><input aria-label="搜索截稿会议" value={search} onChange={e => { setSearch(e.target.value); setSelectedDate(null); }} placeholder="模糊查找会议、领域或地点，不区分大小写…" /></div><select aria-label="截稿会议领域" value={area} onChange={e => { setArea(e.target.value); setSelectedDate(null); }}><option value="">全部 CCF 领域</option>{areas.map(value => <option key={value}>{value}</option>)}</select><select aria-label="日历时区" value={timezone} onChange={e => { setTimezone(e.target.value); setSelectedDate(null); }}><option value="Asia/Shanghai">北京时间 UTC+8</option><option value="UTC">协调世界时 UTC</option></select></div>
        <div className="deadline-status-row"><div role="group" aria-label="截稿状态">{STATUS.map(item => <button key={item.id} aria-pressed={status === item.id} className={status === item.id ? "active" : ""} onClick={() => { setStatus(item.id); setSelectedDate(null); }}>{item.label}</button>)}</div><span>{filtered.length} 个匹配轮次</span></div>
        {view === "calendar" && status !== "tba" && <>
          <div className="calendar-heading"><div><button className="icon-button" aria-label="上个月" onClick={() => updateMonth(adjacentMonth(month, -1))}><Icon name="back" size={17} /></button><h2>{Number(month.slice(0, 4))} 年 <span>{Number(month.slice(5))} 月</span></h2><button className="icon-button" aria-label="下个月" onClick={() => updateMonth(adjacentMonth(month, 1))}><Icon name="arrow" size={17} /></button><button className="calendar-today" onClick={() => updateMonth(activeDate.slice(0, 7))}>本月</button></div><span><i className="calendar-legend-a" />A 类 <i className="calendar-legend-b" />B 类</span></div>
          <div className="calendar-weekdays" aria-hidden="true">{WEEKDAYS.map(day => <span key={day}>{day}</span>)}</div>
          <div className="calendar-grid" aria-label={`${month} 截稿日期`}>
            {cells.map(cell => { const dayEvents = byDate.get(cell.key) || []; return <button key={cell.key} className={`calendar-day ${!cell.inMonth ? "outside" : ""} ${cell.key === activeDate ? "today" : ""} ${cell.key === selectedDate ? "selected" : ""}`} aria-label={`${cell.key}，${dayEvents.length} 个截稿节点`} aria-pressed={cell.key === selectedDate} onClick={() => setSelectedDate(selectedDate === cell.key ? null : cell.key)}><span className="calendar-day-number">{cell.day}{cell.key === activeDate && <small>今天</small>}</span><span className="calendar-events">{dayEvents.slice(0, 2).map(event => <span key={event.id} className={`calendar-event level-${event.level.toLowerCase()}`}><i />{event.venue}</span>)}{dayEvents.length > 2 && <span className="calendar-more">+{dayEvents.length - 2} 个节点</span>}</span>{dayEvents.length > 0 && <span className="calendar-mobile-count">{dayEvents.length}</span>}</button>; })}
          </div>
        </>}
      </section>
      <div className="deadline-results-heading"><div><h2>{view === "list" || status === "tba" ? "投稿时间线" : selectedDate ? `${selectedDate} · 截稿详情` : "本月投稿时间线"}<span>{displayed.length}</span></h2><p>{selectedDate ? "再次点击日期可取消选择。" : "全文截稿按所选时区排序；AoE 为 UTC−12，已换算为上方时区。"}</p></div><button className="button secondary small-button" disabled={!displayed.some(e => e.deadline_utc)} onClick={exportCalendar}><Icon name="calendar" size={15} />导出当前结果 .ics</button></div>
      {exported && <p className="deadline-export-message" role="status">日历文件已生成。导出的是当前结果的全文截稿节点，摘要时间写入事件说明；这不是自动更新的订阅。</p>}
      {displayed.length ? <div className="deadline-list">{displayed.map(event => <DeadlineCard key={event.id} event={event} now={now} timezone={timezone} />)}</div> : <EmptyState title={selectedDate ? "这一天没有匹配的截稿节点" : view === "calendar" && status !== "tba" ? "本月没有匹配的截稿节点" : "暂时没有匹配的投稿轮次"} message="可以切换月份、列表视图或清除筛选。没有记录不代表该会议没有截稿安排。" />}
      <div className="deadline-bottom-note"><p><a href={data.source.url} target="_blank" rel="noopener noreferrer">CCFDDL 社区数据 <Icon name="external" size={12} /></a><span> · </span><a href={`${import.meta.env.BASE_URL}data-sources/CCFDDL-LICENSE.txt`} target="_blank" rel="noopener noreferrer">MIT 许可</a> · 会议级别使用本站 CCF 2026 目录。期刊通常全年投稿，不混入会议截稿倒计时。</p>{data.coverage.missing_venues.length > 0 && <details><summary>{data.coverage.missing_venues.length} 个会议未匹配到当年或未来届次，暂不推测日期</summary><p>{data.coverage.missing_venues.join(" · ")}</p></details>}</div>
    </>}
  </div>;
}
