import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { validateCoverageSnapshot, validateAssociations } from '../src/data/source-coverage.js';

const snapshot = process.env.SNAPSHOT_DIR ? pathToFileURL(resolve(process.env.SNAPSHOT_DIR) + '/') : new URL('../static/snapshot/', import.meta.url);
const directory = process.env.COVERAGE_DIR ? pathToFileURL(resolve(process.env.COVERAGE_DIR) + '/') : new URL('../static/data-sources/', import.meta.url);
const manifest = JSON.parse(await readFile(new URL('manifest.json', snapshot)));
const data = validateCoverageSnapshot(JSON.parse(await readFile(new URL('source-coverage.json', directory))), manifest);
const catalogBytes = await readFile(new URL(manifest.catalog.path, snapshot));
assert.equal(createHash('sha256').update(catalogBytes).digest('hex'), manifest.catalog.sha256);
const catalog = JSON.parse(catalogBytes), venues = new Map(catalog.venues.map(venue => [venue.abbr, venue]));
assert.equal(data.sources.length, venues.size);
let associations = 0;
for (const source of data.sources) {
  const venue = venues.get(source.abbr);
  assert.ok(venue, 'Unconfigured source: ' + source.abbr);
  for (const field of ['name', 'type', 'level']) assert.equal(source[field], venue[field]);
  const expected = Object.entries(catalog.conference_associations?.[source.abbr] || {})
    .flatMap(([year, ids]) => ids.map(id => id + ':' + year)).sort();
  if (!source.associations) {
    assert.equal(expected.length, 0, 'Missing conference associations: ' + source.abbr);
    continue;
  }
  const bytes = await readFile(new URL(source.associations.path, directory));
  assert.equal(createHash('sha256').update(bytes).digest('hex'), source.associations.sha256);
  const linked = validateAssociations(JSON.parse(bytes), source, manifest.revision);
  assert.deepEqual(linked.papers.map(paper => paper.id + ':' + paper.event_year).sort(), expected);
  associations++;
}
console.log(JSON.stringify({ revision: manifest.revision, paper_count: data.snapshot_papers,
  sources: data.configured_sources, association_files: associations }));
