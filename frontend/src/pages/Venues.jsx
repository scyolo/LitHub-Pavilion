import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useDashboard } from "../hooks/useResearchData.js";
import { useFilters } from "../hooks/useFilters.js";
import { scopeParams } from "../lib/presentation.js";
import Icon from "../components/Icon.jsx";
import ScopeTabs from "../components/ScopeTabs.jsx";
import VenueDirectory from "../components/VenueDirectory.jsx";
import { ErrorState, LoadingState } from "../components/States.jsx";

export default function Venues() {
  const { filters, update } = useFilters();
  const [directoryFilters, setDirectoryFilters] = useState({ search: "", sort: "count", area: "" });
  const scope = scopeParams(filters);
  const dashboard = useDashboard(scope);
  const signatures = useQuery({ queryKey: ["venue-topics", scope], queryFn: ({ signal }) => api.venueTopics(scope, signal), enabled: Boolean(api.venueTopics) });
  return <div className="venues-page page-enter">
    <div className="page-heading"><div><div className="eyebrow"><span className="tiny-line" />VENUE ATLAS</div><h1>找到你关注的<span>学术坐标。</span></h1><p>只看 CCF A / B 顶会顶刊：按学科定位来源，再看每个研究社区的真实主题分布。</p></div><div className="page-heading-tag"><Icon name="building" size={16} />{dashboard.data?.configured_venues ?? "—"} 个配置来源</div></div>
    <div className="data-notice"><Icon name="info" size={16}/><span>部分会议论文以期刊形式发表，原论文不重复入库。</span><Link to="/coverage" className="text-button">查看全部来源覆盖与官网证据 →</Link></div>
    <ScopeTabs filters={filters} onChange={update} />
    {dashboard.isPending ? <LoadingState rows={3} /> : dashboard.error ? <ErrorState message={dashboard.error.message} onRetry={() => dashboard.refetch()} /> : <section aria-label="会议与期刊目录" className="venue-atlas-directory">
      <h2 className="sr-only">会议与期刊目录</h2>
      <VenueDirectory venues={dashboard.data.venues} directions={dashboard.data.directions} signatures={signatures.data?.items} scope={scope} filters={directoryFilters} onFiltersChange={setDirectoryFilters} />
    </section>}
    <div className="data-notice"><Icon name="info" size={16} /><span>仅配置 CCF 官方目录中的 A / B 类会议和期刊，不收集 C 类或目录外来源。新增来源分批回填；“来源已配置”不等于“论文已收录”，零记录也不代表该来源没有正式发表论文。主题标签来自论文统计，不是来源的唯一研究方向。</span></div>
  </div>;
}
