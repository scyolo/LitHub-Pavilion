// Public metadata only. A cache error never prevents ordinary browsing.
const NAME = "lithub-verified-overview-v1";
const MAX_BYTES = 10 * 1024 * 1024;
const bounded = (operation, fallback) => new Promise(resolve => {
  const timer = setTimeout(() => resolve(fallback), 250);
  Promise.resolve().then(operation).then(value => { clearTimeout(timer); resolve(value); }, () => { clearTimeout(timer); resolve(fallback); });
});
export function createOverviewCache(baseUrl) {
  const key = new URL(".verified-overview", baseUrl).href;
  return {
    read: () => bounded(async () => {
      if (!globalThis.caches) return null;
      const response = await (await caches.open(NAME)).match(key);
      if (!response) return null;
      const text = await response.text();
      return text.length > MAX_BYTES ? null : JSON.parse(text);
    }, null),
    write: value => bounded(async () => {
      if (!globalThis.caches) return;
      const text = JSON.stringify(value);
      if (new TextEncoder().encode(text).byteLength > MAX_BYTES) return;
      await (await caches.open(NAME)).put(key, new Response(text, { headers: { "Content-Type": "application/json" } }));
    }),
    clear: () => bounded(async () => { if (globalThis.caches) await (await caches.open(NAME)).delete(key); }),
  };
}
