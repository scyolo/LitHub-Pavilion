// Discovery only: fuzzy matches must never be used to merge publication identities.
export function normalizeSearchText(value) {
  return String(value ?? "").normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

function oneEditApart(left, right) {
  if (Math.abs(left.length - right.length) > 1) return false;
  let index = 0;
  while (index < left.length && left[index] === right[index]) index++;
  if (index === Math.min(left.length, right.length)) return true;
  if (left.length < right.length) return left.slice(index) === right.slice(index + 1);
  if (left.length > right.length) return left.slice(index + 1) === right.slice(index);
  return left.slice(index + 1) === right.slice(index + 1)
    || (left[index] === right[index + 1] && left[index + 1] === right[index]
      && left.slice(index + 2) === right.slice(index + 2));
}

function textMatcher(query) {
  if (!String(query ?? "").trim()) return () => 0;
  const normalized = normalizeSearchText(query);
  if (!normalized) return () => null;
  const compact = normalized.replaceAll(" ", "");
  const tokens = [...new Set(normalized.split(" "))];
  return (fields) => {
    const values = fields.map(normalizeSearchText).filter(Boolean);
    if (values[0] === normalized) return 0;
    if (values.includes(normalized)) return 1;
    if (values.some(value => value.includes(normalized))) return 2;
    if (values.some(value => value.replaceAll(" ", "").includes(compact))) return 3;
    if (/^[a-z0-9]{4,32}$/.test(compact) && values.some(value => oneEditApart(compact, value.replaceAll(" ", "")))) return 5;
    const words = [...new Set(values.flatMap(value => value.split(" ")))];
    let approximate = 0;
    for (const token of tokens) {
      if (values.some(value => value.includes(token))) continue;
      // Keep short acronyms and Chinese text literal; bound typo work per word.
      if (/^[a-z0-9]{4,32}$/.test(token) && words.some(word => oneEditApart(token, word))) approximate++;
      else return null;
    }
    return approximate ? 4 + approximate : 4;
  };
}

export function matchesText(query, fields) {
  return textMatcher(query)(fields) !== null;
}

export function searchVenues(venues, query = "", sort = "count") {
  const score = textMatcher(query);
  return venues.map(venue => ({ venue, score: score([venue.abbr, venue.name, venue.ccf_area]) }))
    .filter(result => result.score !== null)
    .sort((a, b) => a.score - b.score
      || (sort === "area" ? (a.venue.ccf_area || "").localeCompare(b.venue.ccf_area || "", "zh-CN") : 0)
      || (sort === "name" ? 0 : (b.venue.paper_count || 0) - (a.venue.paper_count || 0))
      || a.venue.abbr.localeCompare(b.venue.abbr, "en", { sensitivity: "base" }))
    .map(result => result.venue);
}
