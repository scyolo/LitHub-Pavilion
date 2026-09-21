export const TOPICS = {
  llm: { name: "大语言模型", short: "LLM", icon: "sparkles", color: "#79b7ff" },
  specdec: { name: "投机解码", short: "Speculative Decoding", icon: "bolt", color: "#9c96ff" },
  agent: { name: "智能体", short: "AI Agents", icon: "nodes", color: "#61d9b7" },
  cv: { name: "计算机视觉", short: "Computer Vision", icon: "scan", color: "#efb97a" },
  multimodal: { name: "多模态学习", short: "Multimodal", icon: "layers", color: "#7cd1e0" },
  rl: { name: "强化学习", short: "Reinforcement Learning", icon: "route", color: "#b1c57f" },
  nlp: { name: "自然语言处理", short: "NLP", icon: "text", color: "#c7a2e8" },
  retrieval: { name: "信息检索与 RAG", short: "Retrieval & RAG", icon: "search", color: "#ed9fae" },
  alignment: { name: "安全与对齐", short: "Safety & Alignment", icon: "shield", color: "#86b5c8" },
};

export const SCOPES = [
  { id: "all", label: "全部 A / B", level: "", type: "" },
  { id: "a-conf", label: "A 类会议", level: "A", type: "conf" },
  { id: "b-conf", label: "B 类会议", level: "B", type: "conf" },
  { id: "a-journal", label: "A 类期刊", level: "A", type: "journal" },
  { id: "b-journal", label: "B 类期刊", level: "B", type: "journal" },
];

export function topic(code, name) {
  return TOPICS[code] || { name: name || code, short: code, icon: "layers", color: "#9ba8ba" };
}

export function number(value) {
  return value !== null && value !== undefined && Number.isFinite(Number(value)) ? new Intl.NumberFormat("zh-CN").format(Number(value)) : "—";
}

export function compact(value) {
  const n = Number(value) || 0;
  return n >= 10000 ? `${(n / 10000).toFixed(1)}万` : number(n);
}

export function percent(part, total) {
  return total > 0 ? `${Math.round((part / total) * 100)}%` : "—";
}

export function formatDate(value, includeTime = false) {
  if (!value) return "暂无记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "日期未知";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    ...(includeTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
  }).format(date);
}

export function safeExternalUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value.trim());
    if (!new Set(["http:", "https:"]).has(url.protocol) || url.username || url.password) return null;
    const host = url.hostname.toLowerCase().replace(/\.$/, "");
    if (!host || host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local") || host.endsWith(".localdomain")) return null;
    if (/^(127\.|10\.|192\.168\.|169\.254\.|0\.)/.test(host)) return null;
    if (/^172\.(1[6-9]|2\d|3[01])\./.test(host) || host.includes(":")) return null;
    return url.href;
  } catch {
    return null;
  }
}

export function paperLinks(paper) {
  const arxiv = /^\d{4}\.\d{4,5}(v\d+)?$/.test(paper.arxiv_id || "")
    ? `https://arxiv.org/abs/${paper.arxiv_id}` : null;
  return {
    official: safeExternalUrl(paper.official_url),
    oa: safeExternalUrl(paper.oa_url) || arxiv,
  };
}

export function paperHref(id, params = {}) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v != null));
  return `${id ? `/papers/${id}` : "/papers"}${qs.size ? `?${qs}` : ""}`;
}

export function parseFilters(search) {
  const params = new URLSearchParams(search);
  const page = Number(params.get("page"));
  const size = Number(params.get("size"));
  const allowedSorts = ["relevance", "created_desc", "year_desc", "citation_desc"];
  const sort = params.get("sort");
  return {
    q: params.get("q") || "",
    level: ["A", "B"].includes(params.get("level")) ? params.get("level") : "",
    type: ["conf", "journal"].includes(params.get("type")) ? params.get("type") : "",
    direction: params.get("direction") || "",
    venue: params.get("venue") || "",
    year: params.get("year") || "",
    access: ["oa", "official"].includes(params.get("access")) ? params.get("access") : "",
    sort: allowedSorts.includes(sort) ? sort : (params.get("q") ? "relevance" : "created_desc"),
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    size: [10, 20, 50].includes(size) ? size : 20,
  };
}

export function filteredParams(filters) {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== "" && value != null));
}

export function scopeParams(filters) {
  return filteredParams({ level: filters.level, type: filters.type });
}
