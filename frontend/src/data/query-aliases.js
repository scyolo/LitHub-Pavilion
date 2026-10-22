import aliases from "./query_aliases.json" with { type: "json" };

export function queryKey(value) {
  return value.normalize("NFKC").toLowerCase().trim().replace(/\s+/g, " ");
}

export function keywordQuery(value) {
  return typeof value === "string" && value.length <= 300 ? aliases.keywords[queryKey(value)] || value : value;
}

export function queryTopic(value, mode, directions = []) {
  if (typeof value !== "string" || value.length > 300 || mode === "exact" || !/[\u3400-\u4dbf\u4e00-\u9fff]/u.test(value)) return null;
  const key = queryKey(value), code = aliases.topics[key];
  return directions.find(d => d.enabled !== 0 && d.enabled !== false && (d.code === code || queryKey(d.name || "") === key)) || null;
}
