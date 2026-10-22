import { safeExternalUrl } from '../lib/presentation.js';

export default function AcceptedPapers({items = []}) {
  if (!items.length) return null;
  return <section className="accepted-references" aria-label="官方已录用，出版待核验">
    <p className="data-notice">找到 {items.length} 条专题录用记录。以下论文已获官方录用确认，正式出版信息待核实，单列展示。</p>
    <div className="paper-stack">{items.map(item => <article className="paper-card accepted-reference" key={item.reference_id}>
      <div className="paper-card-body">
        <p className="paper-authors">录用会议：{item.venue} · {item.year} · CCF {item.level}</p>
        <a className="paper-title" href={safeExternalUrl(item.preprint_url || item.official_url)} target="_blank" rel="noopener noreferrer">{item.title}</a>
        <p className="paper-authors">{item.authors.join('；')}</p>
        <div className="paper-actions"><span className="venue-empty">官方已录用 · 出版待核验</span>
          <a className="paper-external" href={safeExternalUrl(item.official_url)} target="_blank" rel="noopener noreferrer">官方录用证据</a>
          {item.preprint_url && <a className="paper-external" href={safeExternalUrl(item.preprint_url)} target="_blank" rel="noopener noreferrer">已核实预印本</a>}
        </div>
      </div>
    </article>)}</div>
  </section>;
}
