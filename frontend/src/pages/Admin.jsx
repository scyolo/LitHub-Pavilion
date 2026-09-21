import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useCrawlStatus, useDashboard } from "../hooks/useResearchData.js";
import { formatDate, number, percent } from "../lib/presentation.js";
import Icon from "../components/Icon.jsx";
import { ErrorState, LoadingState, SectionTitle } from "../components/States.jsx";

const STATES = { running: "运行中", interrupted: "未正常结束", success: "已完成", partial: "部分完成", failed: "失败" };
const TYPES = { weekly: "周增量", backfill: "历史回填", reclassify: "方向重算", monthly: "引用更新", pdf_backlog: "旧版 PDF 任务" };

export default function Admin() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [notice, setNotice] = useState("");
  const [confirmBackfill, setConfirmBackfill] = useState(false);
  const statusQuery = useCrawlStatus();
  const status = statusQuery.data;
  const lastRunning = useRef(false);
  const dashboard = useDashboard();
  const logs = useQuery({ queryKey: ["crawl-logs", page], queryFn: ({ signal }) => api.crawlLogs(page, signal), refetchInterval: status?.running ? 6000 : false });
  const start = useMutation({ mutationFn: api.trigger, onSuccess: (data) => { setNotice(`任务已提交：${data.run_id}`); queryClient.invalidateQueries({ queryKey: ["crawl-status"] }); queryClient.invalidateQueries({ queryKey: ["crawl-logs"] }); }, onError: (error) => setNotice(`提交失败：${error.message}`) });
  useEffect(() => {
    if (lastRunning.current && !status?.running) {
      for (const key of ["dashboard", "papers", "directions", "crawl-logs"]) queryClient.invalidateQueries({ queryKey: [key] });
    }
    lastRunning.current = Boolean(status?.running);
  }, [status?.running, queryClient]);
  const progressParts = status?.progress?.split("/").map(Number) || [];
  const progress = progressParts.length === 2 && progressParts[1] > 0 ? Math.min(100, progressParts[0] / progressParts[1] * 100) : 0;
  const busy = Boolean(status?.running || start.isPending || statusQuery.isPending || statusQuery.error);
  function runStatus(run) {
    if (status && run.status === "running" && !(status.running && status.run_id === run.run_id)) return "interrupted";
    if (dashboard.data?.last_crawl?.run_id === run.run_id) return dashboard.data.last_crawl.status;
    return run.status;
  }

  return <div className="admin-page page-enter">
    <div className="page-heading"><div><div className="eyebrow"><span className="tiny-line" />SYNC CENTER</div><h1>让追踪，<span>持续发生。</span></h1><p>采集运行状态、更新计划与来源缺口，都在这里。</p></div><span className="page-heading-tag"><Icon name="shield" size={16} />本地 · 无需登录</span></div>
    {statusQuery.error ? <ErrorState message={statusQuery.error.message} onRetry={() => statusQuery.refetch()} /> : <div className="admin-summary">
      <section className="panel run-panel"><SectionTitle icon="refresh" title="采集状态"><span className={`run-state ${status?.running ? "running" : "idle"}`}><i />{status?.running ? "正在同步" : "当前空闲"}</span></SectionTitle><h3>{status?.running ? status.current || "准备采集任务…" : "让系统为你持续发现研究"}</h3><p>{status?.running ? `任务 ${status.run_id || "准备中"}` : "每周采集一次；图表刷新只查询本地数据，不额外请求论文源。"}</p>{status?.running && <div className="run-progress"><div role="progressbar" aria-label="采集进度" aria-valuenow={Math.round(progress)} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${progress}%` }} /></div><small>{status.progress || "等待上游响应"}</small></div>}<div className="run-actions"><button className="button primary" onClick={() => start.mutate({ scope: "weekly" })} disabled={busy}><Icon name="refresh" size={16} className={start.isPending ? "spin" : ""} />立即同步元数据</button><button className="button secondary" onClick={() => setConfirmBackfill(!confirmBackfill)} disabled={busy}>回填 2023–2025</button></div>{confirmBackfill && <div className="confirm-box"><p>历史回填会请求外部 API，按已完成单元续传。确认启动？</p><button className="button secondary small-button" disabled={busy} onClick={() => { setConfirmBackfill(false); start.mutate({ scope: "backfill", years: [2023, 2024, 2025] }); }}>确认回填</button><button className="text-button" onClick={() => setConfirmBackfill(false)}>取消</button></div>}{notice && <p className="action-notice" role="status">{notice}</p>}{status?.last_error && <p className="action-error" role="alert">最近错误：{status.last_error}</p>}</section>
      <section className="panel schedule-panel"><SectionTitle icon="calendar" title="更新计划" /><dl><div><dt><span className="status-dot" />论文元数据</dt><dd>{status?.schedule?.next_crawl_at ? formatDate(status.schedule.next_crawl_at, true) : "每周一 04:00"}<small>下次采集 · {status?.schedule?.timezone || "Asia/Shanghai"}</small></dd></div><div><dt><Icon name="link" size={14} />开放链接补全</dt><dd>{status?.schedule?.next_links_at ? formatDate(status.schedule.next_links_at, true) : "每周二 06:30"}<small>只更新链接，不存储文件</small></dd></div></dl><div className="schedule-note"><Icon name="shield" size={17} /><p>链接模式已启用<br /><span>官方 / OA 跳转，不下载 PDF</span></p></div></section>
    </div>}
    {dashboard.data && <div className="quality-strip"><div><strong>{number(dashboard.data.total)}</strong><span>已收录论文</span></div><div><strong>{percent(dashboard.data.with_abstract, dashboard.data.total)}</strong><span>摘要覆盖</span></div><div><strong>{percent(dashboard.data.with_oa_link, dashboard.data.total)}</strong><span>开放链接覆盖</span></div><div><strong>{dashboard.data.venues_with_papers} / {dashboard.data.configured_venues}</strong><span>有数据的配置来源</span></div><Link to="/venues" className="text-link">检查来源缺口<Icon name="arrow" size={15} /></Link></div>}
    <section className="panel logs-panel"><SectionTitle icon="clock" title="采集历史" note="真实运行记录；部分失败的单元不会计作完整覆盖"><button className="icon-button" aria-label="刷新采集日志" onClick={() => logs.refetch()}><Icon name="refresh" size={17} /></button></SectionTitle>{logs.isPending ? <LoadingState rows={2} /> : logs.error ? <ErrorState message={logs.error.message} onRetry={() => logs.refetch()} /> : <><div className="table-scroll"><table><thead><tr><th>任务</th><th>状态</th><th>新增论文</th><th>更新记录</th><th>开始时间</th><th>结束时间</th></tr></thead><tbody>{logs.data?.items.map((run) => <tr key={`${run.run_id}-${run.started_at}`}><td><strong>{TYPES[run.task_type] || run.task_type}</strong><small className="run-id">{run.run_id}</small>{run.error && <details className="log-details"><summary>查看运行详情</summary><p>{run.error}</p></details>}</td><td><span className={`log-status ${runStatus(run)}`}>{STATES[runStatus(run)] || runStatus(run)}</span></td><td className="numeric">{number(run.papers_new)}</td><td className="numeric">{number(run.papers_updated)}</td><td>{formatDate(run.started_at, true)}</td><td>{run.finished_at ? formatDate(run.finished_at, true) : "尚未记录"}</td></tr>)}</tbody></table></div>{logs.data?.items.length === 0 && <p className="muted logs-empty">暂无采集日志。可以手动同步一次元数据。</p>}<div className="pagination"><span>{number(logs.data?.total)} 次运行记录</span><div><button className="icon-button" aria-label="上一页日志" disabled={page <= 1} onClick={() => setPage(page - 1)}><Icon name="back" size={16} /></button><span>{page}</span><button className="icon-button" aria-label="下一页日志" disabled={page * 10 >= (logs.data?.total || 0)} onClick={() => setPage(page + 1)}><Icon name="arrow" size={16} /></button></div></div></>}</section>
    <div className="data-notice"><Icon name="info" size={16} /><span>API 限流、来源映射与索引延迟都可能造成收录缺口。请以会议、期刊官方页面确认正式发表信息。</span></div>
  </div>;
}
