import { stemmer } from "stemmer";
import { expandTokens } from "./fuzzy-terms.js";
import { normalizedTitle, parseParams, queryTokens, readerError } from "./snapshot-engine.js";

const invalid = () => readerError("分页索引校验失败，请重新发布快照", 503, "INVALID_SNAPSHOT");

// Search postings supply global DF/TF and title positions. Filtering/sorting
// needs only compact numeric rows, never every candidate's display card.
export function createRankedReader({ descriptor, manifest, catalog, batches, cards, chunk, bucket, selectedEntries }) {
  const ranking = descriptor.ranking, venues = new Map(catalog.venues.map(v => [v.abbr, v]));
  if (ranking?.version !== 1 || !Array.isArray(ranking.parts) || ranking.parts.length > 4096
      || ranking.parts.reduce((s, p) => s + p.count, 0) !== manifest.paper_count
      || !Array.isArray(ranking.venues) || ranking.venues.some(v => !venues.has(v))
      || !Array.isArray(ranking.directions) || ranking.directions.some(d => typeof d !== 'string')
      || !Array.isArray(ranking.pdf_statuses)) throw invalid();
  for (const part of ranking.parts) if (!/^[0-9a-f]{64}$/.test(part.sha256)
      || part.path !== 'ranking-' + part.sha256 + '.json.gz'
      || !Number.isSafeInteger(part.count) || part.count < 1
      || !Number.isSafeInteger(part.min_id) || !Number.isSafeInteger(part.max_id)
      || part.min_id < 1 || part.max_id < part.min_id) throw invalid();
  const rankParts = new Map(), queries = new Map();
  let vocabulary;
  async function rankRows(ids, filters) {
    const scoped = filters.venue || filters.year || filters.level || filters.type || filters.directions.length;
    const ranges = scoped ? [] : null;
    if (scoped) for (const range of selectedEntries(filters).map(part=>[part.min_id,part.max_id]).sort((a,b)=>a[0]-b[0])) {
      const previous=ranges.at(-1);
      if(previous&&range[0]<=previous[1]+1)previous[1]=Math.max(previous[1],range[1]);else ranges.push(range);
    }
    function inScope(id) {
      if (!ranges) return true;
      let lo=0,hi=ranges.length;
      while(lo<hi){const mid=(lo+hi)>>>1;if(ranges[mid][1]<id)lo=mid+1;else hi=mid;}
      return lo<ranges.length && ranges[lo][0]<=id;
    }
    if (ids && scoped) ids = new Set([...ids].filter(inScope));
    const sorted = ids ? [...ids].sort((a,b)=>a-b) : null;
    const parts = ranking.parts.filter(p => (!ranges || ranges.some(([low,high])=>low<=p.max_id&&high>=p.min_id)) && (!sorted || overlaps(p, sorted)));
    for (const part of parts) if (!rankParts.has(part.path)) {
      const promise = chunk(part).then(rows => {
        let id = 0;
        const records = rows.map(row => {
          if (!Array.isArray(row) || row.length !== 9 || !row.filter((_, i)=>i!==6).every(Number.isSafeInteger)
              || row[0] < 1 || row[1] < 0 || row[1] >= ranking.venues.length || row[2] < 1 || row[2] > 9999
              || row[3] < 0 || row[4] < 0 || row[5] < 0 || row[7] < 0 || row[7] >= ranking.pdf_statuses.length
              || ![0,1].includes(row[8]) || !Array.isArray(row[6])
              || row[6].some(d=>!Number.isSafeInteger(d)||d<0||d>=ranking.directions.length)) throw invalid();
          id += row[0];
          if (!Number.isSafeInteger(id)) throw invalid();
          return [id, ...row.slice(1)];
        });
        if (records[0]?.[0] !== part.min_id || id !== part.max_id) throw invalid();
        return records;
      });
      rankParts.set(part.path, promise);
      promise.catch(()=>{if(rankParts.get(part.path)===promise)rankParts.delete(part.path);});
    }
    const result = (await Promise.all(parts.map(p=>rankParts.get(p.path)))).flat();
    const selected = ids ? result.filter(row=>ids.has(row[0])) : result;
    if ((ids && selected.length !== ids.size) || new Set(selected.map(row=>row[0])).size !== selected.length) throw invalid();
    return selected;
  }
  function overlaps(part, sorted) {
    let lo=0,hi=sorted.length;
    while(lo<hi){const mid=(lo+hi)>>>1;if(sorted[mid]<part.min_id)lo=mid+1;else hi=mid;}
    return lo<sorted.length && sorted[lo]<=part.max_id;
  }
  function matches(row, filters) {
    const name=ranking.venues[row[1]],venue=venues.get(name);
    return (!filters.venue || filters.venue===name) && (!filters.level || filters.level===venue.level)
      && (!filters.type || filters.type===venue.type) && (!filters.year || Number(filters.year)===row[2])
      && (!filters.pdf_status || filters.pdf_status===ranking.pdf_statuses[row[7]])
      && (!filters.access || (filters.access==='oa' ? row[8]===1 : row[8]===0))
      && (!filters.directions.length || row[6].some(d=>filters.directions.includes(ranking.directions[d])));
  }
  async function prepare(params, fuzzy) {
    const title=normalizedTitle(params.q), titleRows=await batches(descriptor.search.titles[await bucket(title)]||[]);
    if(titleRows.some(row=>!Array.isArray(row)||row.length!==2||typeof row[0]!=='string'||!Number.isSafeInteger(row[1])||row[1]<1))throw invalid();
    const exact=new Set(titleRows.filter(row=>row[0]===title).map(row=>row[1]));
    const tokens=queryTokens(params.q, params.match==='exact'||exact.size>0), scores=new Map(),priorities=new Map();
    if(params.match==='exact')return {ids:exact,scores:new Map([...exact].map(id=>[id,0])),priorities:new Map([...exact].map(id=>[id,0])),expansions:[],mode:'exact'};
    let tokenGroups=tokens.map(t=>[t]);
    if(fuzzy&&tokens.length){
      if(!vocabulary)vocabulary=batches(descriptor.search.vocabulary).then(rows=>{
        if(rows.some(row=>!Array.isArray(row)||row.length!==2||!/^[a-z0-9]+$/.test(row[0])||!Number.isSafeInteger(row[1])||row[1]<1))throw invalid();
        return rows;
      }).catch(error=>{vocabulary=null;throw error;});
      tokenGroups=expandTokens(tokens,await vocabulary,4,title.match(/[a-z0-9]+/g)||[]);
    }
    const expanded=[...new Set(tokenGroups.flat())],keys=new Set(await Promise.all(expanded.map(t=>bucket(t,3))));
    const rows=await batches([...keys].flatMap(k=>descriptor.search.terms[k]||[]));
    const postings=new Map(expanded.map(t=>[t,new Map()])),positions=new Map(expanded.map(t=>[t,new Map()])),lengths=new Map();
    for(const row of rows){
      if(!Array.isArray(row)||row.length!==5||typeof row[0]!=='string'||!row.slice(1,4).every(Number.isSafeInteger)
          ||row[1]<1||row[2]<1||row[3]<0||!Array.isArray(row[4])||row[4].some((p,i)=>!Number.isSafeInteger(p)||p<0||(i&&p<=row[4][i-1])))throw invalid();
      if(postings.has(row[0])){postings.get(row[0]).set(row[1],row[2]);positions.get(row[0]).set(row[1],row[4]);lengths.set(row[1],row[3]);}
    }
    const groups=tokenGroups.map(terms=>{
      const merged=new Map();for(const term of terms)for(const [id,frequency]of postings.get(term)||[])merged.set(id,Math.max(merged.get(id)||0,frequency));return merged;
    }).sort((a,b)=>a.size-b.size);
    const phrase=(title.match(/[a-z0-9]+/g)||[]).map(t=>stemmer(t)),ids=new Set(exact);
    for(const id of groups[0]?.keys()||[]){
      if(!groups.every(g=>g.has(id)))continue;
      ids.add(id);let score=0;
      for(const group of groups){const frequency=group.get(id),idf=Math.max(1e-6,Math.log((manifest.paper_count-group.size+0.5)/(group.size+0.5)));score-=idf*frequency*2.2/(frequency+1.2*(0.25+0.75*lengths.get(id)/descriptor.search.average_length));}
      const phraseMatch=(positions.get(phrase[0])?.get(id)||[]).some(start=>phrase.every((token,i)=>positions.get(token)?.get(id)?.includes(start+i)));
      priorities.set(id,exact.has(id)?0:phraseMatch?1:tokens.every(t=>positions.get(t)?.get(id)?.length)?2:tokens.every(t=>postings.get(t)?.has(id))?3:4);
      scores.set(id,score);
    }
    for(const id of exact){if(!scores.has(id))scores.set(id,0);priorities.set(id,0);}
    return {ids,scores,priorities,mode:fuzzy?'fuzzy':'keywords',expansions:fuzzy?tokenGroups.map((terms,i)=>({token:tokens[i],alternatives:terms.slice(1)})).filter(r=>r.alternatives.length):[]};
  }
  function query(params,fuzzy){
    if(typeof params.q!=='string'||params.q.length>2000)queryTokens(params.q);
    const key=JSON.stringify([params.q,params.match==='exact',fuzzy]);
    if(!queries.has(key)){const promise=prepare(params,fuzzy);queries.set(key,promise);promise.catch(()=>{if(queries.get(key)===promise)queries.delete(key);});while(queries.size>4)queries.delete(queries.keys().next().value);}
    return queries.get(key);
  }
  return {async call(method, params={}){
    const isSearch=method==='search',filters=parseParams(params,isSearch),mode=params.match||'auto';
    let prepared=isSearch?await query(params,mode==='fuzzy'):null;
    let rows=(await rankRows(prepared?.ids, filters)).filter(row=>matches(row,filters));
    if(isSearch&&mode==='auto'&&!rows.length){prepared=await query(params,true);rows=(await rankRows(prepared.ids, filters)).filter(row=>matches(row,filters));}
    const column={publication_desc:3,created_desc:4,year_desc:2,citation_desc:5}[filters.sort];
    rows.sort((a,b)=>(column?b[column]-a[column]:prepared.priorities.get(a[0])-prepared.priorities.get(b[0])||prepared.scores.get(a[0])-prepared.scores.get(b[0]))||b[0]-a[0]);
    const page=rows.slice((filters.page-1)*filters.size,filters.page*filters.size),ids=new Set(page.map(row=>row[0])),sorted=[...ids].sort((a,b)=>a-b);
    const entries=descriptor.browse.filter(p=>overlaps(p,sorted));
    const loaded=cards((await batches(entries)).filter(row=>ids.has(row[0]))),byId=new Map(loaded.map(row=>[row.id,row]));
    if(byId.size!==ids.size||loaded.length!==ids.size)throw invalid();
    const items=page.map(row=>{const {abstract,authors,direction_details,...card}=byId.get(row[0]);return isSearch?{...card,score:Number(prepared.scores.get(row[0]).toFixed(4))}:card;});
    return {total:rows.length,page:filters.page,size:filters.size,...(isSearch?{match_mode:prepared.mode,query_expansions:prepared.expansions}:{}),items};
  }};
}
