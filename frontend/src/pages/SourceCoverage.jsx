import {useState,useEffect} from 'react';
import {Link,useSearchParams} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {loadCoverage,loadAssociations,zeroYearChecks,COVERAGE_YEARS,ZERO_YEAR_LABELS} from '../data/source-coverage.js';
import {number,formatDate,paperHref} from '../lib/presentation.js';
import {LoadingState,ErrorState,EmptyState} from '../components/States.jsx';
import Icon from '../components/Icon.jsx';
import {matchesText,venueSearchFields} from '../lib/search.js';

function AssociatedPapers({source,revision}) {
  const [visible,setVisible]=useState(30);
  const query=useQuery({queryKey:['source-associations',revision,source.abbr],queryFn:({signal})=>loadAssociations(source,revision,signal),staleTime:Infinity});
  if(query.isPending)return <LoadingState rows={2}/>;
  if(query.error)return <ErrorState message={query.error.message} onRetry={()=>query.refetch()}/>;
  return <section className="coverage-associated" aria-label={source.abbr+' 的关联论文'}><p>这些论文保留原始期刊身份，不重复计入论文总数。会议年份与期刊发表年份分别列出。</p>{query.data.papers.slice(0,visible).map(p=><article className="paper-card" key={p.id+':'+p.event_year}><div className="paper-card-body"><Link className="paper-title" to={'/papers/'+p.id}>{p.title}</Link><p className="paper-authors">原始发表来源：{p.canonical_venue} · 期刊年份 {p.publication_year} · 会议年份 {p.event_year}</p><div className="paper-actions"><a className="paper-external" href={p.official_url} target="_blank" rel="noopener noreferrer">官方原文链接</a><a className="paper-external" href={p.evidence_url} target="_blank" rel="noopener noreferrer">官网目录证据</a></div></div></article>)}{visible<query.data.papers.length&&<button className="button secondary" onClick={()=>setVisible(n=>n+30)}>继续显示关联论文</button>}</section>;
}

function YearEvidence({source,year}) {
  const groups=new Map();
  for(const [value,check] of Object.entries(zeroYearChecks(source))){
    if(year!=='all'&&value!==year)continue;
    const key=JSON.stringify(check);
    if(!groups.has(key))groups.set(key,{check,years:[]});
    groups.get(key).years.push(value);
  }
  if(!groups.size)return null;
  return <ul className="coverage-year-evidence" aria-label={source.abbr+' 的零记录年份核验'}>{[...groups.entries()].map(([key,{check,years}])=><li key={key}>
    <strong>{years.join('、')} · {ZERO_YEAR_LABELS[check.status]}</strong>
    <span>{check.note}</span>
    {check.evidence_url&&<span className="coverage-evidence-links"><a href={check.evidence_url} target="_blank" rel="noopener noreferrer">官方依据</a><small>核验于 {check.checked_at}</small></span>}
    {check.canonical_venue&&<Link className="text-button" to={paperHref(null,{venue:check.canonical_venue,...(years.length===1?{year:years[0]}:{})})}>查询 {check.canonical_venue} 对应届次论文 →</Link>}
  </li>)}</ul>;
}

export default function SourceCoverage(){
  const [params,setParams]=useSearchParams();
  const search=params.get('source')||'';
  const status=['indexed','journal_linked','unresolved','year_gaps'].includes(params.get('status'))?params.get('status'):'all';
  const year=COVERAGE_YEARS.map(String).includes(params.get('year'))?params.get('year'):'all';
  const reason=Object.hasOwn(ZERO_YEAR_LABELS,params.get('reason'))?params.get('reason'):'all';
  const level=['A','B'].includes(params.get('level'))?params.get('level'):'all';
  const setFilter=(key,value)=>{const next=new URLSearchParams(params);if(value&&value!=='all')next.set(key,value);else next.delete(key);setParams(next);};
  const [visible,setVisible]=useState(24);
  const [expanded,setExpanded]=useState(null);
  const query=useQuery({queryKey:['source-coverage'],queryFn:({signal})=>loadCoverage(signal),staleTime:5*60*1000});
  useEffect(()=>setVisible(24),[search,status,year,reason,level]);
  const data=query.data;
  const checks=s=>Object.entries(zeroYearChecks(s)).filter(([y])=>year==='all'||y===year);
  const sources=(data?.sources||[]).filter(s=>(status==='all'||(status==='year_gaps'?checks(s).length>0:s.status===status))&&(level==='all'||s.level===level)&&(reason==='all'||checks(s).some(([,check])=>check.status===reason))&& matchesText(search,venueSearchFields(s)));
  const zeroTotal=(data?.sources||[]).reduce((total,s)=>total+Object.keys(zeroYearChecks(s)).length,0);
  const filteredZeros=sources.reduce((total,s)=>total+checks(s).filter(([,check])=>reason==='all'||check.status===reason).length,0);
  return <div className="coverage-page page-enter"><div className="page-heading"><div><div className="eyebrow"><span className="tiny-line"/>SOURCE COVERAGE</div><h1>覆盖到哪里，<span>证据说清楚。</span></h1><p>逐来源查看直接收录、期刊发表关联与待核验缺口。不把“有论文”当作“已经全量”。</p></div><Link className="button secondary" to="/venues">返回会议与期刊</Link></div>
    {query.isPending?<LoadingState rows={3}/>:query.error?<ErrorState message={query.error.message} onRetry={()=>query.refetch()}/>:<>
    <div className="coverage-summary panel"><div><strong>{number(data.represented_sources)} / {data.configured_sources}</strong><span>已有直接记录或官网关联的来源</span></div><div><strong>{number(data.snapshot_papers)}</strong><span>快照中的唯一论文 · 不重复计数</span></div><div><strong>{data.configured_sources-data.represented_sources}</strong><span>仍待核验的来源</span></div></div>
    <p className="data-notice"><Icon name="info" size={16}/><span>数据截面：{formatDate(data.snapshot_generated_at)}。原始期刊计数与会议关联计数不能相加；零年份可能是未举办、尚未出版或未收录。全量覆盖尚未验证。</span></p>
    <div className="venues-toolbar coverage-toolbar"><div className="search-input"><Icon name="search" size={19}/><input aria-label="搜索覆盖来源" value={search} onChange={e=>setFilter('source',e.target.value)} placeholder="模糊查找来源，不区分大小写…"/></div><select aria-label="覆盖状态" value={status} onChange={e=>setFilter('status',e.target.value)}><option value="all">全部状态</option><option value="indexed">已有直接记录</option><option value="journal_linked">期刊发表关联</option><option value="unresolved">待核验缺口</option><option value="year_gaps">含零记录年份</option></select><select aria-label="覆盖等级" value={level} onChange={e=>setFilter('level',e.target.value)}><option value="all">CCF A / B</option><option value="A">CCF A</option><option value="B">CCF B</option></select><select aria-label="核验年份" value={year} onChange={e=>setFilter('year',e.target.value)}><option value="all">全部年份</option>{COVERAGE_YEARS.map(y=><option key={y} value={y}>{y}</option>)}</select><select aria-label="零记录原因" value={reason} onChange={e=>setFilter('reason',e.target.value)}><option value="all">全部零记录原因</option>{Object.entries(ZERO_YEAR_LABELS).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></div>
    {status==='year_gaps'&&<p className="data-notice"><Icon name="info" size={16}/><span>零记录年份不等于缺失论文：该届可能未举办、尚未出版、联合举办或仍待补采。这里仅用于定位需要进一步核验的范围。</span></p>}
    <p className="venue-result-count">{sources.length} 个匹配来源 · {filteredZeros} 个匹配零记录年份 / 共 {zeroTotal} 个 · 展示 2023–2026 年</p>
    <div className="coverage-source-list">{sources.slice(0,visible).map(s=><section className="panel coverage-source" key={s.abbr}><div className="coverage-source-heading"><div><span className={'level-badge level-'+s.level.toLowerCase()}>CCF {s.level}</span><h2>{s.abbr}</h2><p>{s.name}</p></div><span className={s.status==='unresolved'?'venue-empty':'venue-ready'}>{s.status==='indexed'?'已有直接记录':s.status==='journal_linked'?'已核对期刊发表关联':'待核验 · 不宣称已覆盖'}</span></div>
    <div className="coverage-years">{COVERAGE_YEARS.map(y=><div key={y}><span>{y}</span><strong>{number(s.primary_years[y]||0)}</strong><small>{s.associated_years[y]?number(s.associated_years[y])+' 篇关联':s.primary_years[y]?'直接记录':ZERO_YEAR_LABELS[zeroYearChecks(s)[y].status]}</small></div>)}</div>
    <YearEvidence source={s} year={year}/>
    <div className="coverage-actions">{s.primary_count>0&&<Link className="button secondary" to={paperHref(null,{venue:s.abbr})}>浏览 {number(s.primary_count)} 篇直接记录</Link>}{s.associated_count>0&&<button className="button secondary" aria-label={'查看 '+s.abbr+' 的期刊发表关联'} aria-expanded={expanded===s.abbr} onClick={()=>setExpanded(expanded===s.abbr?null:s.abbr)}>{expanded===s.abbr?'收起':'查看'} {number(s.associated_count)} 篇期刊发表关联</button>}{s.status==='unresolved'&&<span>{s.note||'暂无足够的正式出版证据；不补入预印本、演讲或无关论文。'}{s.evidence_url&&<> <a href={s.evidence_url} target="_blank" rel="noopener noreferrer">来源核验记录</a></>}</span>}</div>
    {s.associated_count>0&&<p><Link className="text-button" to={paperHref(null,{venue:s.abbr,level:s.level,type:s.type,include_associated:'1'})}>在论文探索中查询（含期刊发表关联） →</Link></p>}
    {expanded===s.abbr&&<AssociatedPapers source={s} revision={data.snapshot_revision}/>}</section>)}</div>
    {!sources.length&&<EmptyState title="没有匹配的来源" message="请调整名称或覆盖状态。"/>}{visible<sources.length&&<div className="venues-load-more"><button className="button secondary" onClick={()=>setVisible(n=>n+24)}>继续查看来源（{Math.min(visible,sources.length)} / {sources.length}）</button></div>}
    </>}
  </div>;
}
