import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useDashboard } from "../hooks/useResearchData.js";
import { formatDate, number, percent } from "../lib/presentation.js";
import Icon from "../components/Icon.jsx";
import { ErrorState, LoadingState, SectionTitle } from "../components/States.jsx";

const STATES = { success: "已完成", partial: "部分完成", failed: "失败", running: "未正常结束" };
const TYPES = { weekly: "增量采集", backfill: "历史回填", reclassify: "方向重算", monthly: "引用更新" };

export default function SnapshotAdmin() {
  const [page, setPage] = useState(1);
  const [notice, setNotice] = useState("");
  const [checking, setChecking] = useState(false);
  const dashboard = useDashboard();
  const logs = useQuery({ queryKey: ["crawl-logs", page], queryFn: ({ signal }) => api.crawlLogs(page, signal) });
  const data = dashboard.data;
  async function check() {
    setChecking(true);
    try { setNotice(await api.refreshSnapshot() ? "已载入新的完整快照。" : "当前已是最新发布的快照。"); }
    catch { setNotice("暂时无法检查更新，已有快照仍可继续浏览。"); }
    finally { setChecking(false); }
  }
  return <div className="admin-page page-enter">
    <div className="page-heading"><div><div className="eyebrow"><span className="tiny-line" />SNAPSHOT CENTER</div><h1>随时阅读，<span>按需更新。</span></h1><p>{api.isAuto ? "后端暂未连接，当前使用本地只读快照；连接恢复后会自动切回实时数据。" : "这里展示已发布的论文快照，不连接本地后端。"}</p></div><span className="page-heading-tag"><Icon name="shield" size={16} />静态快照 · 只读</span></div>
    <div className="admin-summary">
      <section className="panel run-panel"><SectionTitle icon="book" title="无需启动 Docker，也能浏览" /><h3>筛选、搜索和原文跳转始终可用</h3><p>交互基于当前快照在浏览器内完成。原文链接直接访问出版方、DOI、DBLP 或开放资源，不经过本地 API。</p><div className="run-actions"><button className="button primary" onClick={check} disabled={checking}><Icon name="refresh" size={16} className={checking ? "spin" : ""} />检查最新快照</button><Link className="button secondary" to="/papers">浏览论文</Link></div>{notice && <p role="status" className="action-notice">{notice}</p>}</section>
      <section className="panel schedule-panel"><SectionTitle icon="calendar" title="数据如何更新" /><dl><div><dt>最近导出</dt><dd>{data ? formatDate(data.generated_at, true) : "正在读取"}<small>这是数据时间，不是页面打开时间</small></dd></div><div><dt>更新方式</dt><dd>启动本地 Docker<small>按配置收集论文、导出快照并触发 GitHub Pages 构建；部署完成后此站点才会更新。</small></dd></div></dl><div className="schedule-note"><Icon name="shield" size={17} /><p>公开站点不执行采集命令<br /><span>采集或发布失败时保留上次成功的数据</span></p></div></section>
    </div>
    {dashboard.error && <ErrorState message={dashboard.error.message} onRetry={() => dashboard.refetch()} />}
    {data && <div className="quality-strip"><div><strong>{number(data.total)}</strong><span>已收录论文</span></div><div><strong>{percent(data.with_abstract, data.total)}</strong><span>摘要覆盖</span></div><div><strong>{percent(data.with_oa_link, data.total)}</strong><span>开放链接覆盖</span></div><div><strong>{data.venues_with_papers} / {data.configured_venues}</strong><span>有数据的配置来源</span></div><Link to="/venues" className="text-link">检查来源缺口<Icon name="arrow" size={15} /></Link></div>}
    <section className="panel logs-panel"><SectionTitle icon="clock" title="快照中的采集历史" note="最近 100 次已结束任务；仅代表导出时状态，不代表本地后端当前运行状态" />
      {logs.isPending ? <LoadingState rows={2} /> : logs.error ? <ErrorState message={logs.error.message} onRetry={() => logs.refetch()} /> : <>
        <div className="table-scroll"><table><thead><tr><th>任务</th><th>状态</th><th>新增论文</th><th>更新记录</th><th>开始时间</th><th>结束时间</th></tr></thead><tbody>{logs.data.items.map((run) => <tr key={`${run.run_id}-${run.started_at}`}><td>{TYPES[run.task_type] || run.task_type}</td><td><span className={`log-status ${run.status}`}>{STATES[run.status] || run.status}</span></td><td>{number(run.papers_new)}</td><td>{number(run.papers_updated)}</td><td>{formatDate(run.started_at, true)}</td><td>{formatDate(run.finished_at, true)}</td></tr>)}</tbody></table></div>
        {!logs.data.items.length && <p className="muted logs-empty">此快照没有已完成的采集日志。</p>}
        <div className="pagination"><span>{number(logs.data.total)} 次任务记录</span><div><button className="icon-button" aria-label="上一页日志" disabled={page <= 1} onClick={() => setPage(page - 1)}><Icon name="back" size={16} /></button><span>{page}</span><button className="icon-button" aria-label="下一页日志" disabled={page * 10 >= logs.data.total} onClick={() => setPage(page + 1)}><Icon name="arrow" size={16} /></button></div></div>
      </>}
    </section>
    <div className="data-notice"><Icon name="info" size={16} /><span>静态快照不含个人备注、数据库文件、PDF 或发布凭据。外站的登录要求、付费限制和资源变更仍由原站决定。</span></div>
  </div>;
}
