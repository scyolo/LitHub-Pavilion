import { readerError } from './reader-errors.js';

const invalid = () => readerError('紧凑检索索引校验失败，请重新发布快照',503,'INVALID_SNAPSHOT');
export function unpackDescriptor(value) {
  if(Array.isArray(value))return value.map(unpackDescriptor);
  if(!value||typeof value!=='object')return value;
  if(Object.hasOwn(value,'$')) {
    const p=value.$;
    if(!Array.isArray(p)||p.length!==3||typeof p[0]!=='string'||!/^[a-z]+$/.test(p[0])
      ||typeof p[1]!=='string'||!/^[0-9a-f]{64}$/.test(p[1])||!Number.isSafeInteger(p[2])||p[2]<0)throw invalid();
    return {path:`${p[0]}-${p[1]}.json.gz`,sha256:p[1],count:p[2],
      ...Object.fromEntries(Object.entries(value).filter(([key])=>key!=='$').map(([key,item])=>[key,unpackDescriptor(item)]))};
  }
  return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,unpackDescriptor(item)]));
}
export function decodeRankingColumns(columns, expectedCount) {
  if (!Array.isArray(columns) || columns.length!==9 || !columns.every(Array.isArray)) throw invalid();
  const count=columns[0].length;
  if ((expectedCount!==undefined&&count!==expectedCount)||columns.some(values=>values.length!==count)) throw invalid();
  const rows=new Array(count);let id=0;
  for(let index=0;index<count;index++) {
    const row=columns.map(values=>values[index]);
    if(!Number.isSafeInteger(row[0])||row[0]<1)throw invalid();
    id+=row[0];if(!Number.isSafeInteger(id))throw invalid();row[0]=id;rows[index]=row;
  }
  return rows;
}
export function decodePostingGroups(groups) {
  const rows=[];
  for(const group of groups) {
    if(!Array.isArray(group)||group.length!==5||typeof group[0]!=='string'
      ||group.slice(1).some(column=>!Array.isArray(column))||group.slice(2).some(column=>column.length!==group[1].length))throw invalid();
    let id=0;
    for(let index=0;index<group[1].length;index++) {
      const delta=group[1][index];if(!Number.isSafeInteger(delta)||delta<1)throw invalid();id+=delta;
      if(!Number.isSafeInteger(id))throw invalid();
      rows.push([group[0],id,group[2][index],group[3][index],group[4][index]]);
    }
  }
  return rows;
}
