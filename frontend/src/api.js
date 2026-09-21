async function request(path, { params, signal, ...options } = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) url.searchParams.set(key, String(value));
  });
  const response = await fetch(url, { signal, ...options });
  const text = await response.text();
  let body;
  try { body = text ? JSON.parse(text) : null; } catch {
    throw new Error("服务返回了非 JSON 内容，请检查本地 API 代理。");
  }
  if (!response.ok) {
    const error = new Error(body?.error?.message || `请求失败（${response.status}）`);
    error.code = body?.error?.code;
    error.status = response.status;
    throw error;
  }
  return body;
}

export const api = {
  papers: (params, signal) => request("/api/papers", { params, signal }),
  paper: (id, signal) => request("/api/papers/" + encodeURIComponent(id), { signal }),
  search: (params, signal) => request("/api/search", { params, signal }),
  dashboard: (params, signal) => request("/api/stats/dashboard", { params, signal }),
  directions: (signal) => request("/api/directions", { signal }),
  venues: (params, signal) => request("/api/venues", { params, signal }),
  stats: (signal) => request("/api/stats/overview", { signal }),
  crawlLogs: (page = 1, signal) => request("/api/crawl/logs", { params: { page, size: 10 }, signal }),
  crawlStatus: (signal) => request("/api/crawl/status", { signal }),
  trigger: (body) => request("/api/crawl/trigger", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }),
};
