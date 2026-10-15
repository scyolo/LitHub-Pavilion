import { lazy } from 'react';

const transient = error => /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Loading chunk .+ failed|Unable to preload CSS/i.test(error?.message || '');

// Browsers may cache a rejected module fetch even when import() is called
// again. Reset that module map once, preserving the current URL and filters.
export function reloadForChunkFailure(options = {}) {
  try {
    const online = options.online ?? globalThis.navigator?.onLine ?? true;
    const version = options.version ?? import.meta.url;
    if (!online || !/^https?:\/\//.test(version)) return false;
    const storage = options.storage ?? globalThis.sessionStorage;
    const key = 'papertracker:chunk-reload';
    if (!storage || storage.getItem(key) === version) return false;
    storage.setItem(key, version);
    (options.reload ?? (() => globalThis.location.reload()))();
    return true;
  } catch { return false; } // Disabled storage must not cause a reload loop.
}

/** Prefetch on navigation intent; retry only transport failures, never app bugs. */
export function createPageModule(importer) {
  let pending;
  function preload() {
    if (!pending) pending = (async () => {
      try { return await importer(); }
      catch (error) {
        if (!transient(error)) throw error;
        await new Promise(resolve => setTimeout(resolve, 350));
        return importer();
      }
    })().catch(error => { pending = null; throw error; });
    return pending;
  }
  const Component = lazy(async () => {
    try { return await preload(); }
    catch (error) {
      // A speculative hover/focus prefetch never reloads the current page.
      // Only a requested route may use the one-shot recovery path.
      if (transient(error)) reloadForChunkFailure();
      throw error;
    }
  });
  return { Component, preload };
}
