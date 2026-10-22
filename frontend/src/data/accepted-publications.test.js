import { expect, it } from 'vitest';
import { snapshotFixture, withOverview } from '../test/snapshot-fixture.js';
import { createSnapshotEngine } from './snapshot-engine.js';
import { createOverview } from './snapshot-overview.js';
import { attachAcceptedReferences, validateAcceptedReferences } from './accepted-publications.js';

export function acceptedFixture() {
  return {reference_id: 'accepted-test-2026', title: 'Accepted Inference System', authors: ['Lee, Ada'],
    venue: 'AC', year: 2026, level: 'A', status: 'accepted_publication_unverified',
    official_url: 'https://conference.example/2026/accepted', preprint_url: null,
    aliases: ['ExampleMethod'], directions: ['llm'], evidence_sha256: 'a'.repeat(64), verified_on: '2026-10-19'};
}

it('returns verified acceptances separately, preserving formal counts and scope', () => {
  const fixture = withOverview(snapshotFixture()), reference = acceptedFixture();
  fixture.catalog.accepted_papers = [reference];
  const engine = createSnapshotEngine(fixture), result = engine.search({q: reference.title, match: 'exact'});
  expect(result.total).toBe(0);
  expect(result.items).toEqual([]);
  expect(result.accepted_items).toEqual([reference]);
  expect(engine.dashboard().total).toBe(3);
  expect(createOverview(fixture).dashboard({}).total).toBe(3);
  for (const params of [{year: 2025}, {type: 'journal'}, {level: 'B'}, {direction: 'agent'}, {access: 'oa'}]) {
    expect(engine.search({q: reference.title, ...params}).accepted_items).toBeUndefined();
  }
  expect(engine.search({q: 'ExampleMethod'}).accepted_items).toEqual([reference]);
  expect(engine.search({q: '大模型', venue: 'AC'})).toMatchObject({match_mode: 'topic', accepted_items: [reference]});
  expect(engine.search({q: 'unrelated-word'}).accepted_items).toBeUndefined();
  expect(attachAcceptedReferences(fixture.catalog, {items: [], total: 0}, '无关中文查询', {venue: 'AC'}).accepted_items).toBeUndefined();
  expect(attachAcceptedReferences(fixture.catalog, {items: [], total: 0}, '', {venue: 'AC'}).accepted_items).toEqual([reference]);
  expect(attachAcceptedReferences(fixture.catalog, {items: [], total: 0}, '', {}).accepted_items).toBeUndefined();
});

it('rejects forged publication status and unsafe or unknown reference sources', () => {
  const fixture = snapshotFixture();
  const reference = acceptedFixture();
  for (const changes of [{status: 'published'}, {venue: 'UNKNOWN'}, {official_url: 'javascript:alert(1)'}, {authors: []}]) {
    expect(() => validateAcceptedReferences([{...reference, ...changes}], fixture.catalog.venues)).toThrow();
  }
});
