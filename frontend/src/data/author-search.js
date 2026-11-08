import { readerError } from './reader-errors.js';
import unicode from './author_unicode.json' with {type:'json'};

function inCategory(char, category) {
  const point=char.codePointAt(0),ranges=unicode[category];
  let low=0,high=ranges.length;
  while(low<high){const middle=(low+high)>>>1;if(ranges[middle][0]<=point)low=middle+1;else high=middle;}
  return low>0&&point<=ranges[low-1][1];
}

// Search normalization is separate from stored author identity and keeps names
// in every script. Complete name words match one author, in any word order.
export function normalizeAuthorName(value) {
  if (/^[\x00-\x7f]*$/u.test(String(value??''))) return String(value??'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
  const assigned=[...String(value??'')].map(char=>inCategory(char,'assigned')?char:' ').join('');
  const lowered=[...assigned.normalize('NFKD')].filter(char=>!inCategory(char,'marks')).join('').toLowerCase();
  return [...lowered].map(char=>inCategory(char,'alphanumeric')?char:' ').join('').replace(/ +/g,' ').trim();
}

export function authorTokens(query) {
  if (typeof query !== 'string' || [...query].length > 200) {
    throw readerError('作者姓名最多 200 字符');
  }
  const normalized = normalizeAuthorName(query);
  if (!normalized) throw readerError('请输入作者姓名', 400, 'EMPTY_QUERY');
  const tokens = normalized.split(' ');
  if (tokens.length > 12) throw readerError('作者姓名最多 12 个词');
  return [...new Set(tokens)];
}

export function matchingAuthors(authors, query) {
  const tokens = authorTokens(query);
  const matched = [];
  for (const author of Array.isArray(authors) ? authors : []) {
    const name = typeof author === 'string' ? author : author?.name;
    if (typeof name !== 'string' || !name.trim()) continue;
    const words = new Set(normalizeAuthorName(name).split(' '));
    if (tokens.every(token => words.has(token)) && !matched.includes(name)) matched.push(name);
  }
  return matched;
}

export function compareAuthorNames(left, right) {
  const a = [...left].map(char => char.codePointAt(0)), b = [...right].map(char => char.codePointAt(0));
  for (let index = 0; index < Math.min(a.length, b.length); index++) if (a[index] !== b[index]) return a[index] - b[index];
  return a.length - b.length;
}
