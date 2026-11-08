import { expect, it } from "vitest";
import { expandTokens, prepareVocabulary } from "./fuzzy-terms.js";

it("completes every query fragment with a bounded set of real title terms", () => {
  expect(expandTokens(["spec", "dec"], [["specul", 12], ["decod", 9]]))
    .toEqual([["spec", "specul"], ["dec", "decod"]]);
  const groups = expandTokens(["mach", "lea"], Array.from({ length: 30 }, (_, i) => ["mach" + i, i + 1]));
  expect(groups.every(group => group.length <= 4)).toBe(true);
  expect(expandTokens(["ai", "ml"], [["aid", 5], ["mlp", 5]])).toEqual([["ai"], ["ml"]]);
});

it('reuses a prepared vocabulary across different queries with identical expansion order', () => {
  const rows = [['specul', 12], ['decod', 9], ['decode', 2], ['spectral', 4], ['learn', 20]];
  const index = prepareVocabulary(rows);
  for (const tokens of [['spec', 'dec'], ['speculativ', 'decodng'], ['lea']]) {
    expect(expandTokens(tokens, index, 4, tokens)).toEqual(expandTokens(tokens, rows, 4, tokens));
    expect(expandTokens(tokens, new Map(rows), 4, tokens)).toEqual(expandTokens(tokens, rows, 4, tokens));
  }
  expect(rows).toEqual([['specul', 12], ['decod', 9], ['decode', 2], ['spectral', 4], ['learn', 20]]);
});

it('losslessly restores a front-coded vocabulary before expanding prefixes and typos',()=>{
  const rows=[['decode',9],['decoding',4],['learn',2]];
  const encoded=[['$vocab',String.fromCodePoint(32,37,32),'decode ing learn',[9,4,2]]];
  const prepared=prepareVocabulary(encoded);
  expect([...prepared.frequencies]).toEqual(rows);
  expect(expandTokens(['dec'],prepared)).toEqual(expandTokens(['dec'],rows));
});
