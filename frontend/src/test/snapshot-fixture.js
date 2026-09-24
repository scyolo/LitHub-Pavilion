export const generated_at = "2026-09-21T08:00:00+00:00";
export function snapshotFixture() {
  const venues = [
    { id: 101, abbr: "AC", name: "A Conference", type: "conf", level: "A", active: 1, ccf_area: "AI" },
    { id: 203, abbr: "BJ", name: "B Journal", type: "journal", level: "B", active: 0, ccf_area: "AI" },
    { id: 305, abbr: "EMPTY", name: "Empty Journal", type: "journal", level: "B", active: 1, ccf_area: "AI" },
  ];
  const directions = [{ code: "llm", name: "大语言模型", enabled: 1 }, { code: "agent", name: "智能体", enabled: 1 }, { code: "unused", name: "未收录", enabled: 1 }];
  const papers = [
    { id: 11, title: "Speculative decoding for models", abstract: "draft ".repeat(90) + "Accelerated inference", venue: "AC", level: "A", year: 2025, directions: ["llm", "agent"], oa_url: "https://arxiv.org/abs/2501.12345", citation_count: 5, created_at: "2026-09-20T00:00:00Z" },
    { id: 23, title: "Agents in planning", abstract: "A model planning system", venue: "BJ", level: "B", year: 2024, directions: ["agent"], oa_url: null, citation_count: 8, created_at: "2026-09-01T00:00:00Z" },
    { id: 35, title: "Speculative model", abstract: "Decoding accelerated inference", venue: "AC", level: "A", year: 2026, directions: ["llm"], oa_url: "https://openreview.net/forum?id=real-id", citation_count: 5, created_at: "2026-09-20T00:00:00Z" },
  ].map((paper) => {
    const venue = venues.find((value) => value.abbr === paper.venue);
    return { publication_date: null, venue_confirmed: false, doi: null, arxiv_id: null, dblp_key: `conf/ac/${paper.id}`, updated_at: generated_at,
      pdf_status: "closed", pdf_source: null, ...paper, venue_name: venue.name, venue_type: venue.type,
      official_url: `https://doi.org/10.5555/paper.${paper.id}`, abstract_preview: paper.abstract.slice(0, 360),
      first_author: "Ada", authors_count: 1, authors_preview: ["Ada"], authors: [{ name: "Ada", order: 1 }],
      direction_details: paper.directions.map((code) => ({ code, name: directions.find((d) => d.code === code).name, score: 2, source: "rule" })),
    };
  });
  return { manifest: { schema_version: 1, generated_at, paper_count: papers.length, revision: "a".repeat(64) }, catalog: { venues, directions, logs: [], last_crawl: null }, papers };
}
