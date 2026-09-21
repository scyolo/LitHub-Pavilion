import { useId } from "react";
import { compact, number, percent, topic } from "../lib/presentation.js";
import { SectionTitle } from "./States.jsx";

export function AnnualChart({ data = [], selectedYear, onSelect }) {
  const titleId = useId();
  const max = Math.max(1, ...data.map((d) => d.total || 0));
  const top = Math.ceil(max / 4) * 4;
  const chartHeight = 154, baseline = 184, left = 50, plot = 565;
  const step = plot / Math.max(data.length, 1);
  return (
    <section className="panel annual-panel">
      <SectionTitle icon="chart" title="年度收录分布" note="按论文归属年份统计 · 点击年份筛选">
        <div className="chart-legend"><span><i className="swatch-a" />A 类</span><span><i className="swatch-b" />B 类</span></div>
      </SectionTitle>
      <div className="annual-chart">
        <svg viewBox="0 0 645 224" role="img" aria-labelledby={titleId}>
          <title id={titleId}>{data.map((d) => `${d.year}年：A类${d.A}篇、B类${d.B}篇`).join("；") || "暂无年度数据"}</title>
          {[0, 1, 2, 3, 4].map((tick) => {
            const y = baseline - (tick / 4) * chartHeight;
            return <g key={tick}><line x1={left} x2="626" y1={y} y2={y} className="chart-grid" /><text x="37" y={y + 4} textAnchor="end" className="chart-axis">{compact((top * tick) / 4)}</text></g>;
          })}
          {data.map((d, i) => {
            const x = left + step * i + step / 2;
            const aH = ((d.A || 0) / top) * chartHeight;
            const bH = ((d.B || 0) / top) * chartHeight;
            const bar = Math.min(33, step * .24);
            return <g key={d.year} className={`chart-year ${String(selectedYear) === String(d.year) ? "selected" : ""}`}>
              <title>{d.year} · A 类 {number(d.A)} · B 类 {number(d.B)}</title>
              <rect className="chart-hit" x={x - step * .44} y="4" width={step * .88} height="217" rx="8" />
              <rect x={x - bar - 3} y={baseline - aH} width={bar} height={aH} rx="4" className="chart-bar-a" />
              <rect x={x + 3} y={baseline - bH} width={bar} height={bH} rx="4" className="chart-bar-b" />
              <text x={x} y={Math.min(baseline - aH, baseline - bH) - 10} textAnchor="middle" className="chart-value">{number(d.total)}</text>
              <text x={x} y="213" textAnchor="middle" className="chart-year-label">{d.year}</text>
            </g>;
          })}
        </svg>
        <div className="annual-controls" style={{ gridTemplateColumns: `repeat(${Math.max(data.length, 1)}, 1fr)` }}>
          {data.map((d) => <button key={d.year} className="chart-year-button" title={`${d.year} · A 类 ${number(d.A)} · B 类 ${number(d.B)}`}
            aria-label={`筛选 ${d.year} 年论文，共 ${number(d.total)} 篇`} onClick={() => onSelect(String(d.year))}><span className="sr-only">{d.year}</span></button>)}
        </div>
      </div>
      <p className="chart-footnote">当前年份尚在收录中；数量为本地已有记录，不代表全年发表总量。</p>
    </section>
  );
}

export function TopicChart({ data = [], onSelect }) {
  const sorted = [...data].sort((a, b) => b.paper_count - a.paper_count).slice(0, 5);
  const max = Math.max(1, ...sorted.map((item) => item.paper_count));
  return <section className="panel topic-panel"><SectionTitle icon="nodes" title="研究主题分布" note="标题与摘要规则归类 · 支持一文多方向" />
    <div className="topic-bars">{sorted.length ? sorted.map((item) => {
      const t = topic(item.code, item.name);
      return <button key={item.code} className="topic-bar-row" onClick={() => onSelect(item.code)} aria-label={`查看${t.name}，${item.paper_count}篇`}>
        <div className="topic-bar-label"><span><i style={{ background: t.color }} />{t.name}</span><strong>{number(item.paper_count)}</strong></div>
        <div className="bar-track"><div style={{ width: `${(item.paper_count / max) * 100}%`, background: t.color }} /></div>
      </button>;
    }) : <p className="muted">暂无方向数据</p>}</div>
    <p className="chart-footnote">方向计数可重叠，不应直接相加作为论文总数。</p>
  </section>;
}

export function LinkCoverage({ total = 0, oa = 0, onSelect }) {
  const value = total ? Math.min(1, oa / total) : 0;
  return <div className="link-coverage">
    <div className="donut-chart"><svg viewBox="0 0 100 100" aria-hidden="true"><circle cx="50" cy="50" r="40" className="donut-track" /><circle cx="50" cy="50" r="40" className="donut-value" strokeDasharray={`${value * 251.33} 251.33`} /></svg><strong>{percent(oa, total)}</strong></div>
    <div><h3>开放链接覆盖</h3><p>{number(oa)} 篇可跳转开放版本</p><button className="text-button" onClick={() => onSelect("oa")}>只看开放获取 →</button></div>
  </div>;
}

export function MiniBars({ years = [] }) {
  const max = Math.max(1, ...years.map((d) => d.count));
  return <div className="mini-bars" aria-hidden="true">{years.map((d) => <span key={d.year} title={`${d.year}: ${number(d.count)}`} style={{ height: `${Math.max(3, d.count / max * 32)}px` }} />)}</div>;
}
