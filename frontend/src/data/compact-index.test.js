import {expect,it} from 'vitest';
import {decodePostingGroups,decodeRankingColumns,unpackDescriptor} from './compact-index.js';

it('decodes column posting groups including record-boundary splits',()=>{
  expect(decodePostingGroups([['learn',[3,7],[8,1],[11,12],[[0],[]]],['learn',[12],[2],[13],[[2]]]]))
    .toEqual([['learn',3,8,11,[0]],['learn',10,1,12,[]],['learn',12,2,13,[2]]]);
});
it('decodes compact rank columns without modifying verified input',()=>{
  const columns=[[3,7],[0,0],[2025,2024],[2,1],[1,2],[5,0],[[0],[0,1]],[0,0],[1,0]];
  const original=structuredClone(columns);
  expect(decodeRankingColumns(columns,2).map(row=>row[0])).toEqual([3,10]);
  expect(columns).toEqual(original);
});
it.each([[[1],[0]],[[0],[0],[2025],[0],[0],[0],[[]],[0],[1]]])('rejects invalid compact rank dimensions or IDs',columns=>{
  expect(()=>decodeRankingColumns(columns)).toThrow();
});
it('expands path pointers from verified compact descriptor bytes',()=>{
  const sha='a'.repeat(64);
  expect(unpackDescriptor({browse:[{$:['browse',sha,128],min_id:1,max_id:150}]})).toEqual(
    {browse:[{path:`browse-${sha}.json.gz`,sha256:sha,count:128,min_id:1,max_id:150}]});
});
