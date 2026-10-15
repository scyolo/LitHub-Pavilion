import { paperDiscoveryLinks, paperLinks } from "../lib/presentation.js";
import Icon from "./Icon.jsx";

const external = { target: "_blank", rel: "noopener noreferrer" };

/** Search routes are deliberately separate from verified full-text evidence. */
export default function PaperAccess({ paper }) {
  const links = paperLinks(paper);
  const preprint = paperLinks({ arxiv_id: paper.arxiv_id }).oa;
  const discoveries = paperDiscoveryLinks(paper);

  return <section className="panel read-panel">
    <div className="read-panel-title"><span className="read-icon"><Icon name="link" size={24} /></span><div><h2>阅读原文</h2><p>直达来源，不在本地存档</p></div></div>
    {links.oa && <a className="button primary full-width" href={links.oa} {...external}><Icon name="book" size={16} />{links.oa === links.official ? "阅读开放全文 · 官方原站" : "阅读开放版本"}<Icon name="external" size={14} /></a>}
    {links.official && links.official !== links.oa && <a className={`button ${links.oa ? "secondary" : "primary"} full-width`} href={links.official} {...external}><Icon name="external" size={16} />访问官方页面<Icon name="arrow" size={16} /></a>}
    {preprint && preprint !== links.oa && preprint !== links.official && <a className="button secondary full-width" href={preprint} {...external}><Icon name="text" size={16} />arXiv 预印本<Icon name="external" size={14} /></a>}
    {!links.official && !links.oa && <p className="muted small">暂无已确认的原文链接，可通过下方入口继续查找。</p>}
    <p className="read-note">{links.oa ? "已找到开放版本入口；预印本与正式出版版本可能存在差异，请核对作者与版本。" : "尚未确认开放版本，不代表没有免费全文；官方页面可能需要出版方权限。"}</p>
    {discoveries.length > 0 && <div className="paper-discovery"><h3><Icon name="search" size={14} />查找更多版本</h3><p>用论文标题继续查找作者稿与机构仓储。</p><div className="paper-discovery-links">{discoveries.map(item => <a key={item.name} href={item.url} {...external}><span>{item.name}<small>{item.note}</small></span><Icon name="external" size={13} /></a>)}</div><p className="discovery-disclaimer">检索入口不计入开放链接覆盖，结果需核对论文身份。</p></div>}
    <div className="read-note"><Icon name="info" size={14} />在新窗口访问原站，本站不下载 PDF。</div>
  </section>;
}
