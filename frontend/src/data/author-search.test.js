import { describe, expect, it } from 'vitest';
import { authorTokens, matchingAuthors, normalizeAuthorName } from './author-search.js';

describe('author name matching', () => {
  it('normalizes accents, full-width letters and punctuation while retaining Chinese names', () => {
    expect(normalizeAuthorName('  BÉNGIO， Ｙｏｓｈｕａ / 张伟  ')).toBe('bengio yoshua 张伟');
    expect(authorTokens('  BÉNGIO， Ｙｏｓｈｕａ  ')).toEqual(['bengio', 'yoshua']);
  });

  it('pins new Unicode assignments to the same search contract as the Python exporter',()=>{
    expect(normalizeAuthorName('\u1c89 Smith')).toBe('smith');
    expect(normalizeAuthorName('\u{1e4d0} Smith')).toBe('smith');
    expect(normalizeAuthorName('Ⓐda Ⅲ')).toBe('ada iii');
    expect(normalizeAuthorName('ΟΣ')).toBe('ος');
  });

  it('matches all complete name words within the same author in either order', () => {
    const authors = [{ name: 'Ada Lovelace', order: 1 }, { name: 'Bengio, Yoshua', order: 4 }];
    expect(matchingAuthors(authors, 'Yoshua Bengio')).toEqual(['Bengio, Yoshua']);
    expect(matchingAuthors(authors, 'BENGIO YOSHUA')).toEqual(['Bengio, Yoshua']);
    expect(matchingAuthors(authors, 'Bengio')).toEqual(['Bengio, Yoshua']);
    expect(matchingAuthors(authors, 'Yosh Bengio')).toEqual([]);
    expect(matchingAuthors(['Yoshua Lee', 'Samy Bengio'], 'Yoshua Bengio')).toEqual([]);
  });

  it('retains every matching author once without claiming to disambiguate people', () => {
    expect(matchingAuthors(['张伟', '张伟', 'Zhang, Wei', '张伟平'], '张伟')).toEqual(['张伟']);
    expect(matchingAuthors(['Yoshua Bengio', 'Bengio, Yoshua'], 'Bengio Yoshua'))
      .toEqual(['Yoshua Bengio', 'Bengio, Yoshua']);
    expect(authorTokens('Bengio Bengio')).toEqual(['bengio']);
  });

  it.each(['', '  ', '？！', '---'])('rejects empty or non-name queries: %s', query => {
    expect(() => authorTokens(query)).toThrowError(expect.objectContaining({status: 400, code: 'EMPTY_QUERY'}));
  });

  it('bounds raw query length and token count before deduplicating', () => {
    expect(() => authorTokens('a'.repeat(201))).toThrowError(expect.objectContaining({status: 400, code: 'INVALID_PARAM'}));
    expect(() => authorTokens(Array(13).fill('Ada').join(' '))).toThrowError(expect.objectContaining({status: 400, code: 'INVALID_PARAM'}));
    expect(() => authorTokens(null)).toThrowError(expect.objectContaining({status: 400, code: 'INVALID_PARAM'}));
    expect(authorTokens('𠮷'.repeat(200))).toHaveLength(1);
  });
});
