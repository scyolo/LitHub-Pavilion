import {expect,it} from 'vitest';
import {keywordQuery,queryTopic} from './query-aliases.js';
import {createSnapshotEngine} from './snapshot-engine.js';
import {snapshotFixture} from '../test/snapshot-fixture.js';

it('only resolves bounded whole-topic and method-name aliases',()=>{
  const fixture=snapshotFixture();
  expect(queryTopic('大模型','auto',fixture.catalog.directions).code).toBe('llm');
  expect(queryTopic('大模型','exact',fixture.catalog.directions)).toBeNull();
  expect(queryTopic('LLM','auto',fixture.catalog.directions)).toBeNull();
  expect(keywordQuery('EAGLE3')).toBe('EAGLE 3');
  expect(keywordQuery('EAGLE3 is in this full title')).toBe('EAGLE3 is in this full title');
});

it('searches Chinese topics using tags and intersects other filters',()=>{
  const engine=createSnapshotEngine(snapshotFixture());
  expect(engine.search({q:'大模型'}).total).toBe(2);
  expect(engine.search({q:'大模型',direction:'agent'}).items.map(p=>p.id)).toEqual([11]);
  expect(engine.search({q:'大模型',year:2023}).total).toBe(0);
});
