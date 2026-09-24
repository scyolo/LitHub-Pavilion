import { useEffect, useRef, useSyncExternalStore } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api.js";
import { formatDate } from "../lib/presentation.js";
import Icon from "./Icon.jsx";

function newClient(snapshot) {
  return new QueryClient({ defaultOptions: { queries: {
    retry: (attempt, error) => error.status >= 400 && error.status < 500 ? false : attempt < 1,
    staleTime: snapshot ? Infinity : 30000,
    refetchOnWindowFocus: !snapshot,
  } } });
}

export default function DataSession({ children }) {
  const source = useSyncExternalStore(api.subscribeData, api.getDataState);
  const state = useSyncExternalStore(api.subscribeSnapshot, api.getSnapshotState);
  const snapshot = source.source === "snapshot";
  const cacheKey = `${source.source}:${source.generation}:${snapshot ? state.revision || "initial" : "live"}`;
  const clients = useRef(new Map());
  if (!clients.current.has(cacheKey)) clients.current.set(cacheKey, newClient(snapshot));
  const current = clients.current.get(cacheKey);
  useEffect(() => {
    for (const [key, previous] of clients.current) {
      if (key !== cacheKey) { previous.clear(); clients.current.delete(key); }
    }
  }, [cacheKey]);
  useEffect(() => {
    if (!api.isAuto) return;
    const check = () => { if (document.visibilityState !== "hidden") api.checkConnection(); };
    check();
    const interval = setInterval(check, 15000);
    window.addEventListener("focus", check);
    return () => { clearInterval(interval); window.removeEventListener("focus", check); };
  }, []);
  useEffect(() => {
    if (!snapshot) return;
    const check = () => { if (document.visibilityState !== "hidden") api.refreshSnapshot().catch(() => {}); };
    const interval = setInterval(check, 60000);
    window.addEventListener("focus", check);
    return () => { clearInterval(interval); window.removeEventListener("focus", check); };
  }, [snapshot]);
  const busy = state.status === "loading" || state.status === "updating";
  const message = state.error
    ? `${state.revision ? "继续使用上次完整快照。" : ""}${state.error}`
    : state.generated_at ? `${api.isAuto ? "后端未连接，正在浏览本地快照" : "公开快照"} · ${formatDate(state.generated_at, true)} · 浏览、检索和原文链接无需本地后端`
      : `正在载入论文快照${state.total ? ` · ${state.loaded} / ${state.total} 个文件` : ""}，本地后端无需启动`;
  return <QueryClientProvider client={current}>
    {snapshot && <div className={`snapshot-banner ${state.error ? "snapshot-warning" : ""}`} role="status">
      <Icon name={state.error ? "info" : "shield"} size={16} /><span>{message}</span>
      {api.isAuto && <button className="button secondary small-button" onClick={() => api.checkConnection()}>连接本地后端</button>}
      <button className="button secondary small-button" disabled={busy} onClick={() => api.refreshSnapshot().catch(() => {})}><Icon name="refresh" size={14} className={busy ? "spin" : ""} />{busy ? "正在检查" : "检查更新"}</button>
    </div>}
    <div key={cacheKey}>{children}</div>
  </QueryClientProvider>;
}
