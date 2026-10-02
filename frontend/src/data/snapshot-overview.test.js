import { expect, it } from "vitest";
import { withOverview } from "../test/snapshot-fixture.js";
import { createOverview } from "./snapshot-overview.js";

function compactFixture() {
  const fixture = withOverview();
  fixture.catalog.overview.version = 2;
  fixture.catalog.overview.venue_topics = { AC: [{ code: "llm", paper_count: 2 }, { code: "agent", paper_count: 1 }], BJ: [{ code: "agent", paper_count: 1 }], EMPTY: [] };
  for (const scope of fixture.catalog.overview.scopes) scope.dashboard.venues = scope.dashboard.venues.map(({ abbr, paper_count, years }) => ({ abbr, paper_count, years }));
  return fixture;
}
it("reconstructs compact source metadata and keeps conference/journal signatures separate", () => {
  const data = compactFixture();
  const overview = createOverview(data);
  expect(overview.dashboard({ level: "A", type: "conf" }).venues[0].name).toBe("A Conference");
  expect(overview.venueTopics({ level: "A", type: "conf" }).items).toEqual({ AC: [{ code: "llm", paper_count: 2 }, { code: "agent", paper_count: 1 }] });
  expect(overview.venueTopics({ level: "B", type: "journal" }).items.AC).toBeUndefined();
  expect(overview.dashboard({}).total).toBe(data.manifest.paper_count);
});
it("keeps legacy snapshots readable without fetching all papers just for topic chips", () => {
  const overview = createOverview(withOverview());
  expect(overview.supports("venueTopics", {})).toBe(true);
  expect(overview.venueTopics({}).items.AC).toEqual([]);
});
it("rejects topic counts greater than the venue's actual public paper count", () => {
  const data = compactFixture();
  data.catalog.overview.venue_topics.AC[0].paper_count = 999;
  expect(() => createOverview(data)).toThrow();
});
