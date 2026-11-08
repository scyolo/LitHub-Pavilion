import { stemmer } from 'stemmer';

const alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789';

function edits(token) {
  const result = new Set();
  if (!/^[a-z0-9]{4,32}$/.test(token)) return result;
  for (let index = 0; index <= token.length; index++) {
    const left = token.slice(0, index), right = token.slice(index);
    if (right) {
      result.add(left + right.slice(1));
      for (const letter of alphabet) result.add(left + letter + right.slice(1));
    }
    for (const letter of alphabet) result.add(left + letter + right);
    if (right.length > 1) result.add(left + right[1] + right[0] + right.slice(2));
  }
  result.delete(token);
  return result;
}

function lowerBound(terms, value) {
  let low = 0, high = terms.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (terms[middle] < value) low = middle + 1; else high = middle;
  }
  return low;
}

export function prepareVocabulary(rows) {
  if(rows[0]?.[0]==='$vocab') {
    const decoded=[];
    for(const row of rows) {
      if(!Array.isArray(row)||row.length!==4||row[0]!=='$vocab'||typeof row[1]!=='string'||typeof row[2]!=='string'||!Array.isArray(row[3]))throw new Error('Invalid compact vocabulary');
      const codes=[...row[1]],suffixes=row[2].split(' ');let previous='';
      if(codes.length!==suffixes.length||codes.length!==row[3].length)throw new Error('Invalid compact vocabulary');
      for(let index=0;index<codes.length;index++) {
        const length=codes[index].codePointAt(0)-32;
        if(length<0||length>previous.length||!Number.isSafeInteger(row[3][index])||row[3][index]<1)throw new Error('Invalid compact vocabulary');
        const word=previous.slice(0,length)+suffixes[index];
        if(!/^[a-z0-9]+$/.test(word)||(index&&word<=previous))throw new Error('Invalid compact vocabulary');
        decoded.push([word,row[3][index]]);previous=word;
      }
    }
    rows=decoded;
  }
  const frequencies = new Map(rows);
  return { frequencies, terms: [...frequencies.keys()].sort() };
}

export function expandTokens(tokens, vocabulary, limit = 4, rawTokens = []) {
  const { frequencies, terms } = vocabulary?.frequencies instanceof Map ? vocabulary : prepareVocabulary(vocabulary);
  const rawByStem = new Map();
  for (const raw of rawTokens) {
    const stem = stemmer(raw);
    if (!rawByStem.has(stem)) rawByStem.set(stem, new Set());
    rawByStem.get(stem).add(raw);
  }
  return tokens.map((token) => {
    const choices = new Map();
    if (frequencies.has(token)) choices.set(token, 0);
    for (const candidate of edits(token)) if (frequencies.has(candidate)) choices.set(candidate, 2);
    // A one-letter raw typo can change the Porter stem by several letters.
    for (const raw of rawByStem.get(token) || []) for (const variant of edits(raw)) {
      const candidate = stemmer(variant);
      if (frequencies.has(candidate) && !choices.has(candidate)) choices.set(candidate, 2);
    }
    // Complete each fragment ("spec dec"), still capped to four real terms per token.
    if (token.length >= 3 && token.length <= 32) {
      for (let i = lowerBound(terms, token), end = lowerBound(terms, token + '{'); i < end; i++) {
        const candidate = terms[i];
        if (candidate.length > token.length) choices.set(candidate, Math.min(choices.get(candidate) ?? 99, 1));
      }
    }
    const ranked = [...choices.keys()].sort((a, b) => choices.get(a) - choices.get(b)
      || frequencies.get(b) - frequencies.get(a) || (a < b ? -1 : a > b ? 1 : 0));
    return [token, ...ranked.filter(value => value !== token).slice(0, limit - 1)];
  });
}
