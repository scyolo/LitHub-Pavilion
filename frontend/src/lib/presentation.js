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
  const text = value.trim();
  if (/[\s\\\u0000-\u001f\u007f<>"]/.test(text) || /%(?:0[0-9a-f]|1[0-9a-f]|7f)/i.test(text) || /%(?![0-9a-f]{2})/i.test(text)) return null;
  try {
    const url = new URL(text);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return null;
    const host = url.hostname.toLowerCase().replace(/\.$/, "");
    if (!host || host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local") || host.endsWith(".localdomain")) return null;
    if (host.includes(":")) return null;
    if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
      const [a, b, c] = host.split(".").map(Number);
      if (a === 0 || a === 10 || a === 127 || a >= 224 || (a === 100 && b >= 64 && b <= 127)
        || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
        || (a === 192 && b === 0 && [0, 2].includes(c)) || (a === 192 && b === 88 && c === 99)
        || (a === 198 && [18, 19].includes(b)) || (a === 198 && b === 51 && c === 100)
        || (a === 203 && b === 0 && c === 113)) return null;
    } else if (!host.includes(".") || !host.split(".").every((label) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))) return null;
    return url.href;
  } catch {
    return null;
  }
}

function doiLink(value) {
  if (typeof value !== "string") return null;
  let id = value.trim();
  if (/^https?:/i.test(id)) {
    const safe = safeExternalUrl(id);
    if (!safe) return null;
    const url = new URL(safe);
    if (!["doi.org", "dx.doi.org"].includes(url.hostname)) return null;
    id = url.pathname.replace(/^\//, "");
  } else id = id.replace(/^doi:\s*/i, "").replace(/^(?:dx\.)?doi\.org\//i, "");
  try { id = decodeURIComponent(id).trim().toLowerCase(); } catch { return null; }
  if (!/^10\.\d{4,9}\/[^\s]+$/.test(id) || /[\\\u0000-\u001f\u007f<>"]/.test(id) || id.split("/").some((part) => [".", ".."].includes(part))) return null;
  return safeExternalUrl("https://doi.org/" + id.split("/").map(encodeURIComponent).join("/"));
}

function arxivLink(value) {
  if (typeof value !== "string") return null;
  let id = value.trim();
  if (/^https?:/i.test(id)) {
    const safe = safeExternalUrl(id);
    if (!safe) return null;
    const url = new URL(safe);
    if (!["arxiv.org", "www.arxiv.org", "export.arxiv.org"].includes(url.hostname) || !/^\/(abs|pdf)\//.test(url.pathname)) return null;
    id = url.pathname.slice(5).replace(/\.pdf$/, "");
  } else id = id.replace(/^arxiv:\s*/i, "");
  return /^(?:\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}|[a-z][a-z.-]*\/\d{7})(?:v[1-9]\d*)?$/i.test(id) ? `https://arxiv.org/abs/${id}` : null;
}

export function paperLinks(paper) {
  const official = safeExternalUrl(paper.official_url);
  const key = typeof paper.dblp_key === "string" ? paper.dblp_key.trim() : "";
  const dblp = /^(?:conf|journals|books|reference|series)\/[A-Za-z0-9._/-]+$/.test(key)
    && key.split("/").length >= 3 && key.split("/").every((part) => part && part !== "." && part !== "..")
    ? `https://dblp.org/rec/${key}` : null;
  return {
    official: doiLink(paper.doi) || (official && ["doi.org", "dx.doi.org"].includes(new URL(official).hostname) ? doiLink(official) : official) || dblp,
    oa: safeExternalUrl(paper.oa_url) || arxivLink(paper.arxiv_id),
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
