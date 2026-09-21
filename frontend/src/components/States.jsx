import Icon from "./Icon.jsx";

export function ErrorState({ message = "暂时无法读取数据。请确认后端服务已启动。", onRetry }) {
  return <div className="state-box state-error" role="alert"><Icon name="info" size={24} /><div><h3>数据暂时不可用</h3><p>{message}</p></div>{onRetry && <button className="button secondary" onClick={onRetry}><Icon name="refresh" size={15} />重新加载</button>}</div>;
}

export function EmptyState({ title = "没有找到符合条件的论文", message = "试试减少筛选条件，或换一个英文关键词。", action }) {
  return <div className="state-box empty-state"><span className="empty-icon"><Icon name="search" size={28} /></span><h3>{title}</h3><p>{message}</p>{action}</div>;
}

export function LoadingState({ rows = 4 }) {
  return <div className="loading-state" role="status" aria-label="正在加载数据">{Array.from({ length: rows }, (_, i) => <div className="skeleton skeleton-card" key={i}><div /><div /><div /></div>)}<span className="sr-only">正在加载数据</span></div>;
}

export function SectionTitle({ icon, title, note, children }) {
  return <div className="section-heading"><div><h2>{icon && <Icon name={icon} size={18} />}{title}</h2>{note && <p>{note}</p>}</div>{children}</div>;
}
