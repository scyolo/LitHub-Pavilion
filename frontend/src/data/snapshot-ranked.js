import { createSharedTasks, throwIfAborted } from "./shared-tasks.js";
import { stemmer } from "stemmer";
import { expandTokens, prepareVocabulary } from "./fuzzy-terms.js";
import { normalizedTitle, parseParams, queryTokens, readerError } from "./snapshot-engine.js";
import { queryTopic } from "./query-aliases.js";
import { createConferenceScope } from './conference-scope.js';
import { acceptedTitleParams, attachAcceptedReferences } from './accepted-publications.js';
import { authorTokens, normalizeAuthorName, compareAuthorNames } from './author-search.js';
import { decodeRankingColumns, decodePostingGroups } from './compact-index.js';

const invalid = () => readerError("分页索引校验失败，请重新发布快照", 503, "INVALID_SNAPSHOT");

// Search postings supply global DF/TF and title positions. Filtering/sorting
// needs only compact numeric rows, never every candidate's display card.
export function createRankedReader({ descriptor, manifest, catalog, batches, cardBatches = batches, cards, chunk, bucket, selectedEntries, downloadAuthorDirectory,lookupEntries }) {
  const ranking = descriptor.ranking, venues = new Map(catalog.venues.map(v => [v.abbr, v]));
  const conferenceScope = createConferenceScope(catalog);
  if (![1,2].includes(ranking?.version) || !Array.isArray(ranking.parts) || ranking.parts.length > 4096
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
  const authorQueries = createSharedTasks({ maxCached: 4 });
  const authorDirectory = createSharedTasks({ maxCached: 1 });
  const candidateRanks = createSharedTasks({ maxCached: 4 });
  const cardHints = createSharedTasks({maxCached:4});
  async function hintedCards(prepared,context) {
    const terms=prepared?.anchorTerms;
    if(!descriptor.search.hints||!terms?.length||!prepared.ids.size)return new Map();
    return cardHints.run(JSON.stringify([...terms].sort()),async shared=>{
      const keys=new Set(await Promise.all(terms.map(term=>bucket(term,3))));
      const groups=await batches(await lookupEntries('hints',keys,shared),shared);
      const result=new Map();
      for(const group of groups) {
        if(!Array.isArray(group)||group.length!==2||typeof group[0]!=='string'||!Array.isArray(group[1]))throw invalid();
        if(!terms.includes(group[0]))continue;
        for(const card of cards(group[1])) {
          const previous=result.get(card.id);
          if(previous&&JSON.stringify(previous)!==JSON.stringify(card))throw invalid();
          result.set(card.id,card);
        }
      }
      return result;
    },context);
  }
  function checkRankingRow(row) {
    if (!Array.isArray(row) || row.length !== 9 || row.some((value,index)=>index!==6&&!Number.isSafeInteger(value))
        || row[0]<1 || row[1]<0 || row[1]>=ranking.venues.length || row[2]<1 || row[2]>9999
        || row[3]<0 || row[4]<0 || row[5]<0 || row[7]<0 || row[7]>=ranking.pdf_statuses.length
        || ![0,1].includes(row[8]) || !Array.isArray(row[6])
        || row[6].some(d=>!Number.isSafeInteger(d)||d<0||d>=ranking.directions.length)) throw invalid();
    return row;
  }
  async function matchingRankRows(prepared,filters,context) {
    if(!prepared.ids.size)return [];
    const terms=prepared.anchorTerms;
    if(!descriptor.search.metadata || !terms?.length)return rankRows(prepared.ids,filters,context);
    const ranks=await candidateRanks.run(JSON.stringify([...terms].sort()),async shared=>{
      const keys=new Set(await Promise.all(terms.map(term=>bucket(term,3))));
      const groups=await batches(await lookupEntries('metadata',keys,shared),shared);
      const result=new Map();
      for(const group of groups) {
        if(!Array.isArray(group)||group.length!==2||typeof group[0]!=='string')throw invalid();
        if(!terms.includes(group[0]))continue;
        for(const row of decodeRankingColumns(group[1])) {
          checkRankingRow(row);
          const previous=result.get(row[0]);
          if(previous&&JSON.stringify(previous)!==JSON.stringify(row))throw invalid();
          result.set(row[0],row);
        }
      }
      return result;
    },context);
    const selected=[],missing=new Set();
    for(const id of prepared.ids) {
      const row=ranks.get(id);
      if(!row){
        if(!prepared.exactIds?.has(id))throw invalid();
        missing.add(id);continue;
      }
      if(matches(row,filters))selected.push(row);
    }
    if(missing.size)selected.push(...await rankRows(missing,filters,context));
    return selected;
  }
  async function authorMatches(q, context) {
    const tokens = authorTokens(q);
    if (!descriptor.search.authors) throw readerError('当前快照尚未建立作者索引，请重新导出或发布新版快照', 503, 'AUTHOR_INDEX_UNAVAILABLE');
    return authorQueries.run(JSON.stringify([...tokens].sort()), async shared => {
      const directory = await authorDirectory.run('index', async loading => {
        const entry = descriptor.search.authors.index;
        const {data} = await downloadAuthorDirectory(entry, loading);
        if (!data || Object.keys(data).sort().join() !== 'bucket_chars,terms,version'
            || data.version !== 1 || data.bucket_chars !== 3 || !data.terms
            || typeof data.terms !== 'object' || Array.isArray(data.terms)
            || Object.keys(data.terms).length > 4096) throw invalid();
        for (const [key, entries] of Object.entries(data.terms)) {
          if (!/^[0-9a-f]{3}$/.test(key) || !Array.isArray(entries) || entries.length > 4096) throw invalid();
          for (const part of entries) if (!/^[0-9a-f]{64}$/.test(part.sha256)
              || part.path !== `author-${part.sha256}.json.gz`
              || !Number.isSafeInteger(part.count) || part.count < 1) throw invalid();
        }
        return data;
      }, shared);
      const keys = new Set(await Promise.all(tokens.map(token => bucket(token, 3))));
      const rows = await batches([...keys].flatMap(key => directory.terms[key] || []), shared);
      const grouped = new Map(tokens.map(token => [token, new Map()]));
      for (const row of rows) {
        if (!Array.isArray(row) || row.length !== 3 || typeof row[0] !== 'string'
            || !/^[\p{L}\p{N}]+$/u.test(row[0]) || typeof row[1] !== 'string' || !row[1]
            || !Array.isArray(row[2]) || !row[2].length
            || row[2].some((id, index) => !Number.isSafeInteger(id) || id < 1 || (index && id <= row[2][index - 1]))) throw invalid();
        const names = grouped.get(row[0]);
        if (!names) continue;
        const words = normalizeAuthorName(row[1]).split(' ');
        if (!words.includes(row[0])) throw invalid();
        // Only names containing every term can match; this prevents different
        // coauthors from satisfying separate words of one requested name.
        if (!tokens.every(token => words.includes(token))) continue;
        if (!names.has(row[1])) names.set(row[1], new Set());
        const ids = names.get(row[1]);
        for (const id of row[2]) {
          if (ids.has(id)) throw invalid();
          ids.add(id);
        }
      }
      const groups = [...grouped.values()].sort((a, b) => a.size - b.size), ids = new Set(), namesById = new Map();
      for (const [name, first] of groups[0] || []) {
        if (!groups.every(group => group.has(name))) continue;
        for (const id of first) {
          if (!groups.every(group => group.get(name).has(id))) continue;
          ids.add(id);
          if (!namesById.has(id)) namesById.set(id, []);
          namesById.get(id).push(name);
        }
      }
      for (const names of namesById.values()) names.sort(compareAuthorNames);
      return {ids, namesById, mode: 'author', expansions: []};
    }, context);
  }
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
      let source = await chunk(part, shared, ranking.version === 2 ? 'ranking' : undefined);
      if (ranking.version === 2) source = decodeRankingColumns(source, part.count);
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
        id = ranking.version === 2 ? row[0] : id + row[0];
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
    const rows = await batches(await lookupEntries('titles',new Set([await bucket(title)]),context), context);
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
        return prepareVocabulary(rows);
      }, context);
      tokenGroups = expandTokens(tokens, terms, 4, title.match(/[a-z0-9]+/g) || []);
    }
    const expanded = [...new Set(tokenGroups.flat())];
    const keys = new Set(await Promise.all(expanded.map(t => bucket(t, 3))));
    let rows = await batches(await lookupEntries('terms',keys,context), context);
    if (descriptor.search.version >= 5) rows = decodePostingGroups(rows);
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
    // Keep one reference to each verified posting. Separate frequency, length,
    // position and single-term merge maps duplicated the same document IDs.
    const postings = new Map(expanded.map(token => [token, new Map()]));
    for (const row of rows) {
      if (!Array.isArray(row) || row.length !== 5 || typeof row[0] !== 'string'
          || !Number.isSafeInteger(row[1]) || !Number.isSafeInteger(row[2]) || !Number.isSafeInteger(row[3])
          || row[1] < 1 || row[2] < 1 || row[3] < 0 || !Array.isArray(row[4])
          || row[4].some((p, i) => !Number.isSafeInteger(p) || p < 0 || (i && p <= row[4][i - 1]))) throw invalid();
      postings.get(row[0])?.set(row[1], row);
    }
    const grouped = tokenGroups.map(terms => {
      if (terms.length === 1) return {terms, rows:postings.get(terms[0])};
      const merged = new Map();
      for (const term of terms) for (const [id, row] of postings.get(term)) {
        if (!merged.has(id) || merged.get(id)[2] < row[2]) merged.set(id, row);
      }
      return {terms, rows:merged};
    }).sort((a, b) => a.rows.size - b.rows.size);
    const groups=grouped.map(group=>group.rows);
    const idfs=groups.map(group=>Math.max(1e-6,Math.log((manifest.paper_count-group.size+0.5)/(group.size+0.5))));
    const phrase=(title.match(/[a-z0-9]+/g)||[]).map(t=>stemmer(t)),ids=new Set(exact);
    for (const [id, first] of groups[0] || []) {
      let score = 0, matches = true;
      const normalization = 1.2 * (0.25 + 0.75 * first[3] / descriptor.search.average_length);
      for (let index = 0; index < groups.length; index++) {
        const row = index === 0 ? first : groups[index].get(id);
        if (!row) { matches = false; break; }
        score -= idfs[index] * row[2] * 2.2 / (row[2] + normalization);
      }
      if (!matches) continue;
      ids.add(id);
      const titlePositions = postings.get(phrase[0])?.get(id)?.[4] || [];
      const phraseMatch = phrase.length === 1 ? titlePositions.length > 0
        : titlePositions.some(start => phrase.every((token, i) => postings.get(token)?.get(id)?.[4].includes(start + i)));
      priorities.set(id, exact.has(id) ? 0 : phraseMatch ? 1
        : tokens.every(token => postings.get(token)?.get(id)?.[4].length) ? 2
        : tokens.every(token => postings.get(token)?.has(id)) ? 3 : 4);
      scores.set(id, score);
    }
    for(const id of exact){if(!scores.has(id))scores.set(id,0);priorities.set(id,0);}
    const anchorTerms = grouped[0]?.terms;
    return {ids,scores,priorities,anchorTerms,exactIds:exact,mode:fuzzy?'fuzzy':'keywords',expansions:fuzzy?tokenGroups.map((terms,i)=>({token:tokens[i],alternatives:terms.slice(1)})).filter(r=>r.alternatives.length):[]};
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
    const authorSearch = isSearch && mode === 'author';
    const selectedTopic=isSearch?queryTopic(params.q,mode,catalog.directions):null;
    filters.queryTopic=selectedTopic?.code || null;
    if((selectedTopic || authorSearch)&&filters.sort==='relevance')filters.sort='publication_desc';
    const { page: pageNumber, size: pageSize, ...scope } = filters;
    const key = JSON.stringify([method, mode, scope]);
    const { rows, prepared, hints } = await ordered.run(key, async shared => {
      let prepared=authorSearch ? await authorMatches(params.q, shared) : selectedTopic?{mode:'topic',expansions:[]}:isSearch?await query(params,mode==='fuzzy',shared):null;
      let rows,hints;
      if(isSearch&&!selectedTopic&&!authorSearch)[rows,hints]=await Promise.all([matchingRankRows(prepared,filters,shared),hintedCards(prepared,shared)]);
      else {rows=await rankRows(prepared?.ids,filters,shared);hints=new Map();}
      if(isSearch&&!selectedTopic&&mode==='auto'&&!rows.length){prepared=await query(params,true,shared);[rows,hints]=await Promise.all([matchingRankRows(prepared,filters,shared),hintedCards(prepared,shared)]);}
      const column={publication_desc:3,created_desc:4,year_desc:2,citation_desc:5}[filters.sort];
      rows.sort((a,b)=>(column?b[column]-a[column]:prepared.priorities.get(a[0])-prepared.priorities.get(b[0])||prepared.scores.get(a[0])-prepared.scores.get(b[0]))||b[0]-a[0]);
      return { rows, prepared, hints };
    }, context);
    throwIfAborted(context.signal);
    const page=rows.slice((filters.page-1)*filters.size,filters.page*filters.size),ids=new Set(page.map(row=>row[0])),sorted=[...ids].sort((a,b)=>a-b);
    for(const row of page) {
      const hinted=hints.get(row[0]);
      if(hinted&&(hinted.venue!==ranking.venues[row[1]]||Number(hinted.year)!==row[2]
        ||!Array.isArray(hinted.directions)||JSON.stringify([...hinted.directions].sort())!==JSON.stringify(row[6].map(d=>ranking.directions[d]).sort())
        ||(hinted.citation_count||0)!==row[5]||hinted.pdf_status!==ranking.pdf_statuses[row[7]]
        ||Number(Boolean(hinted.oa_url))!==row[8]||typeof hinted.title!=='string'))throw invalid();
    }
    const missing=[...ids].filter(id=>!hints.has(id)).sort((a,b)=>a-b),missingIds=new Set(missing);
    const entries=descriptor.browse.filter(p=>overlaps(p,missing));
    const loaded=cards((await cardBatches(entries, context)).filter(row=>missingIds.has(row[0]))),byId=new Map(loaded.map(row=>[row.id,row]));
    if(byId.size!==missingIds.size||loaded.length!==missingIds.size)throw invalid();
    for(const id of ids)if(hints.has(id))byId.set(id,hints.get(id));
    if(byId.size!==ids.size)throw invalid();
    const items=page.map(row=>{const {abstract,authors,direction_details,...card}=byId.get(row[0]);return isSearch?{...card,score:selectedTopic || authorSearch?0:Number(prepared.scores.get(row[0]).toFixed(4)), ...(authorSearch ? {matched_authors: prepared.namesById.get(row[0])} : {})}:card;});
    const result = {total:rows.length,page:filters.page,size:filters.size,...(isSearch?{match_mode:prepared.mode,query_expansions:prepared.expansions}:{}),...(authorSearch ? {effective_sort: filters.sort} : {}),...(selectedTopic?{query_topic:{code:selectedTopic.code,name:selectedTopic.name},effective_sort:filters.sort}:{}),items};
    return attachAcceptedReferences(catalog, result, isSearch ? params.q : '', params);
  }};
}
