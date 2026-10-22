import { createSharedTasks, throwIfAborted } from "./shared-tasks.js";
import { stemmer } from "stemmer";
import { expandTokens } from "./fuzzy-terms.js";
import { normalizedTitle, parseParams, queryTokens, readerError } from "./snapshot-engine.js";
import { queryTopic } from "./query-aliases.js";
import { createConferenceScope } from './conference-scope.js';
import { acceptedTitleParams, attachAcceptedReferences } from './accepted-publications.js';

const invalid = () => readerError("分页索引校验失败，请重新发布快照", 503, "INVALID_SNAPSHOT");

// Search postings supply global DF/TF and title positions. Filtering/sorting
// needs only compact numeric rows, never every candidate's display card.
export function createRankedReader({ descriptor, manifest, catalog, batches, cards, chunk, bucket, selectedEntries }) {
  const ranking = descriptor.ranking, venues = new Map(catalog.venues.map(v => [v.abbr, v]));
  const conferenceScope = createConferenceScope(catalog);
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
  const rankParts = createSharedTasks({ maxCached: 8 }), queries = createSharedTasks({ maxCached: 4 });
  const vocabulary = createSharedTasks({ maxCached: 1 }), ordered = createSharedTasks({ maxCached: 4 });
  async function rankRows(ids, filters, context) {
    const scoped = filters.venue || filters.year || filters.level || filters.type || filters.directions.length || filters.queryTopic;
    const ranges = scoped ? [] : null;
    if (scoped) for (const range of selectedEntries(filters.queryTopic ? {...filters,directions:[filters.queryTopic]} : filters).map(part=>[part.min_id,part.max_id]).sort((a,b)=>a[0]-b[0])) {
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
    const groups = await Promise.all(parts.map(part => rankParts.run(part.path, async shared => {
      const source = await chunk(part, shared);
      const ids = part.max_id <= 0xffffffff ? new Uint32Array(source.length) : new Float64Array(source.length);
      const records = new Array(source.length);
      let id = 0;
      for (let index = 0; index < source.length; index++) {
        const row = source[index];
        if (!Array.isArray(row) || row.length !== 9) throw invalid();
        for (let column = 0; column < 9; column++) {
          if (column !== 6 && !Number.isSafeInteger(row[column])) throw invalid();
        }
        if (row[0] < 1 || row[1] < 0 || row[1] >= ranking.venues.length || row[2] < 1 || row[2] > 9999
            || row[3] < 0 || row[4] < 0 || row[5] < 0 || row[7] < 0 || row[7] >= ranking.pdf_statuses.length
            || ![0, 1].includes(row[8]) || !Array.isArray(row[6])
            || row[6].some(d => !Number.isSafeInteger(d) || d < 0 || d >= ranking.directions.length)) throw invalid();
        id += row[0];
        if (!Number.isSafeInteger(id)) throw invalid();
        ids[index] = id;
        const record = row.slice(); record[0] = id; records[index] = record;
      }
      if (ids[0] !== part.min_id || id !== part.max_id) throw invalid();
      // Decode once, up front: later navigation must not pay deferred row work.
      // One private copy per row replaces the former filter/slice/spread temporaries.
      return { ids, rows: records };
    }, context)));
    throwIfAborted(context.signal);
    const rangesById = parts.map(p => [p.min_id, p.max_id]).sort((a, b) => a[0] - b[0]);
    const disjoint = rangesById.every((range, i) => !i || range[0] > rangesById[i - 1][1]);
    const seen = disjoint ? null : new Set(), selected = [];
    let covered = 0;
    function select(group, index) {
      const id = group.ids[index];
      if (seen?.has(id)) throw invalid();
      seen?.add(id); covered++;
      const row = group.rows[index];
      if (!matches(row, filters)) return;
      selected.push(row);
    }
    function lowerBound(values, value) {
      let low = 0, high = values.length;
      while (low < high) { const mid = (low + high) >>> 1; if (values[mid] < value) low = mid + 1; else high = mid; }
      return low;
    }
    const sparse = sorted && sorted.length * 16 < groups.reduce((count, group) => count + group.ids.length, 0);
    for (const group of groups) {
      if (sparse) {
        // Exact/rare/scoped queries probe compact IDs instead of scanning the corpus.
        for (let pos = lowerBound(sorted, group.ids[0]); pos < sorted.length && sorted[pos] <= group.ids.at(-1); pos++) {
          const index = lowerBound(group.ids, sorted[pos]);
          if (group.ids[index] === sorted[pos]) select(group, index);
        }
      } else {
        for (let index = 0; index < group.ids.length; index++) {
          if (!ids || ids.has(group.ids[index])) select(group, index);
        }
      }
    }
    if (ids && covered !== ids.size) throw invalid();
    return selected;
  }
  function overlaps(part, sorted) {
    let lo=0,hi=sorted.length;
    while(lo<hi){const mid=(lo+hi)>>>1;if(sorted[mid]<part.min_id)lo=mid+1;else hi=mid;}
    return lo<sorted.length && sorted[lo]<=part.max_id;
  }
  function matches(row, filters) {
    const name=ranking.venues[row[1]];
    return conferenceScope.matches(row[0], name, filters) && (!filters.year || Number(filters.year)===row[2])
      && (!filters.pdf_status || filters.pdf_status===ranking.pdf_statuses[row[7]])
      && (!filters.access || (filters.access==='oa' ? row[8]===1 : row[8]===0))
      && (!filters.directions.length || row[6].some(d=>filters.directions.includes(ranking.directions[d])))
      && (!filters.queryTopic || row[6].some(d=>ranking.directions[d]===filters.queryTopic));
  }
  async function titleMatches(title, context) {
    const rows = await batches(descriptor.search.titles[await bucket(title)] || [], context);
    if (rows.some(row => !Array.isArray(row) || row.length !== 2 || typeof row[0] !== 'string'
        || !Number.isSafeInteger(row[1]) || row[1] < 1)) throw invalid();
    return new Set(rows.filter(row => row[0] === title).map(row => row[1]));
  }
  async function termRows(tokens, fuzzy, title, context) {
    let tokenGroups = tokens.map(t => [t]);
    if (fuzzy && tokens.length) {
      const terms = await vocabulary.run("terms", async shared => {
        const rows = await batches(descriptor.search.vocabulary, shared);
        if (rows.some(row => !Array.isArray(row) || row.length !== 2 || !/^[a-z0-9]+$/.test(row[0])
            || !Number.isSafeInteger(row[1]) || row[1] < 1)) throw invalid();
        return rows;
      }, context);
      tokenGroups = expandTokens(tokens, terms, 4, title.match(/[a-z0-9]+/g) || []);
    }
    const expanded = [...new Set(tokenGroups.flat())];
    const keys = new Set(await Promise.all(expanded.map(t => bucket(t, 3))));
    const rows = await batches([...keys].flatMap(k => descriptor.search.terms[k] || []), context);
    return { tokenGroups, expanded, rows };
  }
  async function prepare(params, fuzzy, context) {
    const title = normalizedTitle(params.q), exactPromise = titleMatches(title, context);
    if (params.match === 'exact') {
      const ids = await exactPromise;
      return { ids, scores: new Map([...ids].map(id => [id, 0])), priorities: new Map([...ids].map(id => [id, 0])), expansions: [], mode: 'exact' };
    }
    let tokens, tokenError;
    try { tokens = queryTokens(params.q); } catch (error) { tokenError = error; tokens = []; }
    // Same request budget and shared cancellation scope: do not serialize
    // independent title and posting downloads behind one another's latency.
    const [exact, { tokenGroups, expanded, rows }] = await Promise.all([
      exactPromise, termRows(tokens, fuzzy, title, context),
    ]);
    if (tokenError) tokens = queryTokens(params.q, exact.size > 0);
    const scores = new Map(), priorities = new Map();
    const postings=new Map(expanded.map(t=>[t,new Map()])),positions=new Map(expanded.map(t=>[t,new Map()])),lengths=new Map();
    for(const row of rows){
      if(!Array.isArray(row)||row.length!==5||typeof row[0]!=='string'||!row.slice(1,4).every(Number.isSafeInteger)
          ||row[1]<1||row[2]<1||row[3]<0||!Array.isArray(row[4])||row[4].some((p,i)=>!Number.isSafeInteger(p)||p<0||(i&&p<=row[4][i-1])))throw invalid();
      if(postings.has(row[0])){postings.get(row[0]).set(row[1],row[2]);positions.get(row[0]).set(row[1],row[4]);lengths.set(row[1],row[3]);}
    }
    const groups=tokenGroups.map(terms=>{
      const merged=new Map();for(const term of terms)for(const [id,frequency]of postings.get(term)||[])merged.set(id,Math.max(merged.get(id)||0,frequency));return merged;
    }).sort((a,b)=>a.size-b.size);
    const idfs=groups.map(group=>Math.max(1e-6,Math.log((manifest.paper_count-group.size+0.5)/(group.size+0.5))));
    const phrase=(title.match(/[a-z0-9]+/g)||[]).map(t=>stemmer(t)),ids=new Set(exact);
    for(const id of groups[0]?.keys()||[]){
      if(groups.length>1&&!groups.every(g=>g.has(id)))continue;
      ids.add(id);let score=0;
      for(let index=0;index<groups.length;index++){const frequency=groups[index].get(id);score-=idfs[index]*frequency*2.2/(frequency+1.2*(0.25+0.75*lengths.get(id)/descriptor.search.average_length));}
      const titlePositions=positions.get(phrase[0])?.get(id)||[];
      const phraseMatch=phrase.length===1?titlePositions.length>0:titlePositions.some(start=>phrase.every((token,i)=>positions.get(token)?.get(id)?.includes(start+i)));
      priorities.set(id,exact.has(id)?0:phraseMatch?1:tokens.every(t=>positions.get(t)?.get(id)?.length)?2:tokens.every(t=>postings.get(t)?.has(id))?3:4);
      scores.set(id,score);
    }
    for(const id of exact){if(!scores.has(id))scores.set(id,0);priorities.set(id,0);}
    return {ids,scores,priorities,mode:fuzzy?'fuzzy':'keywords',expansions:fuzzy?tokenGroups.map((terms,i)=>({token:tokens[i],alternatives:terms.slice(1)})).filter(r=>r.alternatives.length):[]};
  }
  function query(params, fuzzy, context) {
    if(typeof params.q!=='string'||params.q.length>2000)queryTokens(params.q);
    const key=JSON.stringify([params.q,params.match==='exact',fuzzy]);
    return queries.run(key, shared => prepare(params, fuzzy, shared), context);
  }
  return {async call(method, params={}, context={}){
    throwIfAborted(context.signal);
    if (method === 'search') params = acceptedTitleParams(catalog, params);
    const isSearch=method==='search',filters=parseParams(params,isSearch),mode=params.match||'auto';
    const selectedTopic=isSearch?queryTopic(params.q,mode,catalog.directions):null;
    filters.queryTopic=selectedTopic?.code || null;
    if(selectedTopic&&filters.sort==='relevance')filters.sort='publication_desc';
    const { page: pageNumber, size: pageSize, ...scope } = filters;
    const key = JSON.stringify([method, mode, scope]);
    const { rows, prepared } = await ordered.run(key, async shared => {
      let prepared=selectedTopic?{mode:'topic',expansions:[]}:isSearch?await query(params,mode==='fuzzy',shared):null;
      let rows=await rankRows(prepared?.ids, filters, shared);
      if(isSearch&&!selectedTopic&&mode==='auto'&&!rows.length){prepared=await query(params,true,shared);rows=await rankRows(prepared.ids, filters, shared);}
      const column={publication_desc:3,created_desc:4,year_desc:2,citation_desc:5}[filters.sort];
      rows.sort((a,b)=>(column?b[column]-a[column]:prepared.priorities.get(a[0])-prepared.priorities.get(b[0])||prepared.scores.get(a[0])-prepared.scores.get(b[0]))||b[0]-a[0]);
      return { rows, prepared };
    }, context);
    throwIfAborted(context.signal);
    const page=rows.slice((filters.page-1)*filters.size,filters.page*filters.size),ids=new Set(page.map(row=>row[0])),sorted=[...ids].sort((a,b)=>a-b);
    const entries=descriptor.browse.filter(p=>overlaps(p,sorted));
    const loaded=cards((await batches(entries, context)).filter(row=>ids.has(row[0]))),byId=new Map(loaded.map(row=>[row.id,row]));
    if(byId.size!==ids.size||loaded.length!==ids.size)throw invalid();
    const items=page.map(row=>{const {abstract,authors,direction_details,...card}=byId.get(row[0]);return isSearch?{...card,score:selectedTopic?0:Number(prepared.scores.get(row[0]).toFixed(4))}:card;});
    const result = {total:rows.length,page:filters.page,size:filters.size,...(isSearch?{match_mode:prepared.mode,query_expansions:prepared.expansions}:{}),...(selectedTopic?{query_topic:{code:selectedTopic.code,name:selectedTopic.name},effective_sort:filters.sort}:{}),items};
    return attachAcceptedReferences(catalog, result, isSearch ? params.q : '', params);
  }};
}
