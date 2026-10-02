import {useState,useEffect} from 'react';
import {Link,useSearchParams} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {loadCoverage,loadAssociations} from '../data/source-coverage.js';
import {number,formatDate,paperHref} from '../lib/presentation.js';
import {LoadingState,ErrorState,EmptyState} from '../components/States.jsx';
import Icon from '../components/Icon.jsx';

function AssociatedPapers({source,revision}) {
  const [visible,setVisible]=useState(30);
  const query=useQuery({queryKey:['source-associations',revision,source.abbr],queryFn:({signal})=>loadAssociations(source,revision,signal),staleTime:Infinity});
  if(query.isPending)return <LoadingState rows={2}/>;
  if(query.error)return <ErrorState message={query.error.message} onRetry={()=>query.refetch()}/>;
  return <section className="coverage-associated" aria-label={source.abbr+' 的关联论文'}><p>这些论文保留原始期刊身份，不重复计入论文总数。会议年份与期刊发表年份分别列出。</p>{query.data.papers.slice(0,visible).map(p=><article className="paper-card" key={p.id+':'+p.event_year}><div className="paper-card-body"><Link className="paper-title" to={'/papers/'+p.id}>{p.title}</Link><p className="paper-authors">原始发表来源：{p.canonical_venue} · 期刊年份 {p.publication_year} · 会议年份 {p.event_year}</p><div className="paper-actions"><a className="paper-external" href={p.official_url} target="_blank" rel="noopener noreferrer">官方原文链接</a><a className="paper-external" href={p.evidence_url} target="_blank" rel="noopener noreferrer">官网目录证据</a></div></div></article>)}{visible<query.data.papers.length&&<button className="button secondary" onClick={()=>setVisible(n=>n+30)}>继续显示关联论文</button>}</section>;
}

export default function SourceCoverage(){
  const [params,setParams]=useSearchParams();
  const search=params.get('source')||'';
  const status=['indexed','journal_linked','unresolved','year_gaps'].includes(params.get('status'))?params.get('status'):'all';
  const setFilter=(key,value)=>{const next=new URLSearchParams(params);if(value&&value!=='all')next.set(key,value);else next.delete(key);setParams(next);};
  const [visible,setVisible]=useState(24);
  const [expanded,setExpanded]=useState(null);
  const query=useQuery({queryKey:['source-coverage'],queryFn:({signal})=>loadCoverage(signal),staleTime:5*60*1000});
  useEffect(()=>setVisible(24),[search,status]);
  const data=query.data;
  const zeroYears=s=>[2023,2024,2025,2026].filter(y=>!(s.primary_years[y]||s.associated_years[y]));
  const sources=(data?.sources||[]).filter(s=>(status==='all'||(status==='year_gaps'?zeroYears(s).length>0:s.status===status))&& (s.abbr+' '+s.name).toLowerCase().includes(search.trim().toLowerCase()));
  return <div className="coverage-page page-enter"><div className="page-heading"><div><div className="eyebrow"><span className="tiny-line"/>SOURCE COVERAGE</div><h1>覆盖到哪里，<span>证据说清楚。</span></h1><p>逐来源查看直接收录、期刊发表关联与待核验缺口。不把“有论文”当作“已经全量”。</p></div><Link className="button secondary" to="/venues">返回会议与期刊</Link></div>
    {query.isPending?<LoadingState rows={3}/>:query.error?<ErrorState message={query.error.message} onRetry={()=>query.refetch()}/>:<>
    <div className="coverage-summary panel"><div><strong>{number(data.represented_sources)} / {data.configured_sources}</strong><span>已有直接记录或官网关联的来源</span></div><div><strong>{number(data.snapshot_papers)}</strong><span>快照中的唯一论文 · 不重复计数</span></div><div><strong>{data.configured_sources-data.represented_sources}</strong><span>仍待核验的来源</span></div></div>
    <p className="data-notice"><Icon name="info" size={16}/><span>数据截面：{formatDate(data.snapshot_generated_at)}。原始期刊计数与会议关联计数不能相加；零年份可能是未举办、尚未出版或未收录。全量覆盖尚未验证。</span></p>
    <div className="venues-toolbar"><div className="search-input"><Icon name="search" size={19}/><input aria-label="搜索覆盖来源" value={search} onChange={e=>setFilter('source',e.target.value)} placeholder="查找来源，例如 Eurographics、SIGGRAPH…"/></div><select aria-label="覆盖状态" value={status} onChange={e=>setFilter('status',e.target.value)}><option value="all">全部状态</option><option value="indexed">已有直接记录</option><option value="journal_linked">期刊发表关联</option><option value="unresolved">待核验缺口</option><option value="year_gaps">含零记录年份</option></select></div>
    {status==='year_gaps'&&<p className="data-notice"><Icon name="info" size={16}/><span>零记录年份不等于缺失论文：该届可能未举办、尚未出版、联合举办或仍待补采。这里仅用于定位需要进一步核验的范围。</span></p>}
    <p className="venue-result-count">{sources.length} 个匹配来源 · 展示 2023–2026 年</p>
    <div className="coverage-source-list">{sources.slice(0,visible).map(s=><section className="panel coverage-source" key={s.abbr}><div className="coverage-source-heading"><div><span className={'level-badge level-'+s.level.toLowerCase()}>CCF {s.level}</span><h2>{s.abbr}</h2><p>{s.name}</p></div><span className={s.status==='unresolved'?'venue-empty':'venue-ready'}>{s.status==='indexed'?'已有直接记录':s.status==='journal_linked'?'已核对期刊发表关联':'待核验 · 不宣称已覆盖'}</span></div>
    <div className="coverage-years">{[2023,2024,2025,2026].map(y=><div key={y}><span>{y}</span><strong>{number(s.primary_years[y]||0)}</strong><small>{s.associated_years[y]?number(s.associated_years[y])+' 篇关联':'直接记录'}</small></div>)}</div>
    <div className="coverage-actions">{s.primary_count>0&&<Link className="button secondary" to={paperHref(null,{venue:s.abbr})}>浏览 {number(s.primary_count)} 篇直接记录</Link>}{s.associated_count>0&&<button className="button secondary" aria-label={'查看 '+s.abbr+' 的期刊发表关联'} aria-expanded={expanded===s.abbr} onClick={()=>setExpanded(expanded===s.abbr?null:s.abbr)}>{expanded===s.abbr?'收起':'查看'} {number(s.associated_count)} 篇期刊发表关联</button>}{s.status==='unresolved'&&<span>{s.note||'暂无足够的正式出版证据；不补入预印本、演讲或无关论文。'}{s.evidence_url&&<> <a href={s.evidence_url} target="_blank" rel="noopener noreferrer">来源核验记录</a></>}</span>}</div>
    {expanded===s.abbr&&<AssociatedPapers source={s} revision={data.snapshot_revision}/>}</section>)}</div>
    {!sources.length&&<EmptyState title="没有匹配的来源" message="请调整名称或覆盖状态。"/>}{visible<sources.length&&<div className="venues-load-more"><button className="button secondary" onClick={()=>setVisible(n=>n+24)}>继续查看来源（{Math.min(visible,sources.length)} / {sources.length}）</button></div>}
    </>}
  </div>;
}
