import { expect, it } from 'vitest';
import { snapshotFixture, withOverview } from '../test/snapshot-fixture.js';
import { createSnapshotEngine } from './snapshot-engine.js';
import { createOverview } from './snapshot-overview.js';
import { createConferenceScope } from './conference-scope.js';

function linkedFixture() {
  const fixture = withOverview(snapshotFixture());
  // Use a configured conference whose canonical publications are level A,
  // while the verified journal paper keeps its own B classification/year.
  fixture.catalog.conference_associations = {AC: {'2025': [23], '2026': [23]}};
  return fixture;
}

it('includes exact conference affiliations on opt-in, with one original journal identity', () => {
  const fixture = linkedFixture(), engine = createSnapshotEngine(fixture);
  const result = engine.search({q: 'Agents in planning', venue: 'AC', level: 'A', type: 'conf', include_associated: '1', year: 2024});
  expect(result.items.map(p => p.id)).toEqual([23]);
  expect(result.items[0]).toMatchObject({venue: 'BJ', level: 'B', year: 2024});
  expect(engine.search({q: 'Agents in planning', venue: 'AC'}).total).toBe(0);
  expect(engine.search({q: 'Agents in planning', venue: 'AC', include_associated: '1', year: 2025}).total).toBe(0);
  expect(engine.search({q: 'Agents in planning', venue: 'AC', include_associated: '1', level: 'B'}).total).toBe(0);
  expect(engine.search({q: 'Agents in planning', venue: 'AC', include_associated: '1', type: 'journal'}).total).toBe(0);
  expect(engine.dashboard().total).toBe(3);
  expect(engine.dashboard({type: 'conf'}).total).toBe(2);
});

it('adds source lookup counts without changing canonical dashboard totals or year arrays', () => {
  const fixture = linkedFixture(), full = createSnapshotEngine(fixture), overview = createOverview(fixture);
  expect(overview.dashboard({type: 'conf'})).toEqual(full.dashboard({type: 'conf'}));
  const venue = overview.venues({}).items.find(v => v.abbr === 'AC');
  expect(venue).toMatchObject({paper_count: 2, associated_paper_count: 1});
  expect(venue.years.reduce((sum, y) => sum + y.count, 0)).toBe(2);
});

it('rejects malformed or unconfigured association references', () => {
  for (const associations of [{NOPE: {'2025': [23]}}, {BJ: {'2025': [23]}}, {AC: {'2025': [23, 23]}}, {AC: {'2025': [-1]}}, {AC: {'../2025': [23]}}]) {
    const fixture = snapshotFixture();
    fixture.catalog.conference_associations = associations;
    expect(() => createConferenceScope(fixture.catalog)).toThrow();
  }
});
