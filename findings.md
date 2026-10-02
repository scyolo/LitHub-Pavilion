# Findings — current continuation

- User explicitly requires metadata and original publication links only. No PDF/full-text or whole-database archive downloads. Previous abandoned partial archive stays untouched; the earlier bulk-download plan is obsolete.
- Workspace contains extensive prior uncommitted work on main; preserve it and do not automatically commit, push, or deploy.
- Original task: 338 configured CCF A/B sources, 16 directions, 2023–2026. Beginning of this continuation: local database 187,041 papers / 81 nonempty sources; existing LOCAL static snapshot still 141,496 public papers / 43 sources.
- Per-source jobs are resumable but registry_enumerated is NOT publisher-wide completeness. Public admission may exclude database records; keep those counts separate.
- Conference discovery previously stopped after any nonempty fuzzy candidate search, even when no exact source matched. Now unions full name/acronym/stream aliases and checks explicit event year (not imprint year).
- Generic catalog recognition must not override publisher/track-specific DOI constraints for ACL, EMNLP, COLING, AAAI, ICAPS, IJCAI, KR, ECAI, ECML-PKDD, ICRA.
- All 11 previously unresolved journal ISSNs now have live registry evidence; five need exact explicit publisher-name variants rather than fuzzy matching.
- Same 141,496-paper search scenario: 45,991,855 -> 29,238,317 transferred bytes; 229 -> 165 requests; 5,089 -> 3,595 ms. These are local-file simulation results, not network/mobile guarantees.
- Reader v4 moves the large reader descriptor outside homepage metadata and loads it only for browsing/search. New generated snapshot is being validated before any local replacement.
- A .venv Windows python launcher and its child are ONE job. Verify parent/child relationships before treating processes as duplicates.

## Latest substantive source evidence (2026-10-02)
- Performance2023 official list: https://performance2023.sciencesconf.org/resource/page/id/6; 2025: https://performance2025.sciencesconf.org/resource/page/id/3.2025 policy page id13 states PEVA long papers and PER short/abstracts; do not treat whole PEVA volume as a conference.
- SPM2023 official program migrated to https://sites.google.com/view/spm-2023/program, discovered via https://igs2023.imati.cnr.it/ linked by GMP2023/Eurographics.23 main papers,11 exact canonical CAD associations. Do not reuse sites.google.com/view/spm-2024 or -2025: those are unrelated signal-processing conferences.
- Crossref query cursor pages overlap and can truncate large conference coverage under strict inventory semantics. New bounded offset adapter tolerates duplicate hits, keeps exact title filter, caps reads and never claims completeness.ICASSP recovered8,285 total new papers across all retried scopes (see report for per-source split).
- CIDR2025 uses https://vldb.org/cidrdb/papers/2025/ absolute links; CIDR2026 uses https://www.cidrdb.org/cidr2026/papers/.These were earlier missed by relative-only parser.
- Final verified local snapshot368,122; coverage336/338; remaining LISA,VEE require official scope determination. Full inventory completeness still unproven even for represented sources.

## Source/year audit 2026-10-02
- Nonempty source counts concealed54 truly zero-record year scopes that could be filled with exact evidence this batch. Keep year-level audit separate from source-level presence and full-list completeness.
- Serial primary/e-ISSN equivalence and2025 IEEE/ACM->IEEE title changes matter: exact legacy/new serial maps recovered years without broad fuzzy titles.
- Crossref labels some INFORMSJoC .cd code/data repository DOIs as journal-article, even with the exact original research title. Public metadata gate now rejects these DOI identities; raw records stay intact.
- PACMHCI switched to numeric issues. Do not infer a meeting from the number alone. Public programs.sigchi.org offers conference-data JSON explicitly (no personal data); use published main-paper types and exact registered DOI/title/authors, exclude draft/poster/workshop and known future publication dates.
- PODS research began appearing in PACMMOD; generic all-PACMMOD->SIGMOD caused wrong source/CCF A labeling. Official2024/2025 PODS lists justify76 narrowly guarded corrections to PODS/B (same ID and DOI) and an explicit DOI provenance map.
- Current remaining-source-years.json has117 zero-record scopes including6 already-known calendar exceptions. LISA/VEE are still unresolved target-year editions; MPLR site lists PPPJ/ManLang history, not evidence that VEE should be replaced by MPLR.

## 2026-10-02 final coverage/performance checkpoint

- Middleware2023 metadata has a literal on ZZZ parent title and 18 split subtitle fields; official DOI-bound title/author evidence resolves24 papers without fuzzy normalization. WWW2025 SIGWEB OpenTOC is only100 records; 87 intersect the official408 research-poster list and match identities. SIGGRAPH2025 exact parent yields174 and excludes195 other-parent records.
- Public corpus381,441; represented336/338; zero source/year units114. LISA/VEE remain unverified rather than synthesized. Snapshot revision 3d798240bffdabc2ac5bc4d601610a03568e1327b7879db36e5417c600d33938.
- Broad search bottleneck was card hydration before ranking, not just slow fetch. New ranking/position indexes preserve existing results/scores while fetching only the requested page. Hard timeout needs a shared retry rule: PaperList had its own override and otherwise retried after12s. Real blocked-network QA now proves one attempt and successful manual recovery.
- Frontend public association files had been hidden by the generic coverage/ ignore rule; explicit exceptions now preserve source coverage on checkout.
- Current source branch is codex/coverage-search-performance-20261002; main auto-deploys, so source submission is deliberately separate from site-data/Pages publication. Tests892/177, metadata479101B/2requests, title identities381441, referenced asset hashes6614 pass. Docker daemon unavailable; no claim of local container smoke.

## Resume verification (2026-10-02)

- All 892 backend and 177 frontend tests passed again, as did Ruff and the production build. Same snapshot revision and all 381,441 title identities passed the independent search check; homepage metadata remains 479,101 B / 2 requests / no paper chunks.
- The unfinished stable mobile detail check now passes at 390x844: no horizontal overflow, hidden sidebar right edge 0, canonical title and DOI retained, no page errors. Screenshot visually inspected after transitions finished.
- Remaining 114 zero-record source/year units split into 13 (2023), 8 (2024), 15 (2025), and 78 (2026). Existing schedule annotations are not proof of completeness or absence. No new publication records have been imported in this resumption.
- Staged secret-pattern scan found no private-key/token matches or forbidden files. Credential-URL candidates are explicit rejection-test fixtures under example domains/arXiv, not runtime credentials.

- Fresh browser recheck after rebuild: local homepage 197 ms; learning cold search 763 ms. Shared 4 Mbps + 80 ms latency + 4x main-thread CPU slowdown: homepage 1,486 ms, learning 5,537 ms, slowest tested search (fuzzy) 5,921 ms. All seven cold/warm budget cases passed without page errors or overflow. These are controlled local preview measurements, not public-host latency guarantees. Weak-network mobile screenshot visually inspected.

- Final read-only DB check independently confirms 381,441 admitted papers out of 389,630 stored records, all title identities queryable, 33 exact and 16 scattered-AND checks. Snapshot hashes 6,614 and current association hashes 12 pass with no writes. Timeout regression confirms 12,277 ms, one attempt, 914 ms manual recovery.
