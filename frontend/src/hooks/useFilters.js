import { useSearchParams } from "react-router-dom";
import { parseFilters } from "../lib/presentation.js";

export function useFilters() {
  const [params, setParams] = useSearchParams();
  const filters = parseFilters(params.toString());
  function update(changes, { resetPage = true, replace = false } = {}) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      Object.entries(changes).forEach(([key, value]) => {
        if (value === "" || value === null || value === undefined) next.delete(key);
        else next.set(key, String(value));
      });
      if (resetPage) next.delete("page");
      if (Object.hasOwn(changes, "q") && !String(changes.q || "").trim() && next.get("sort") === "relevance") next.delete("sort");
      return next;
    }, { replace });
  }
  function toggleDirection(code) {
    const values = new Set(filters.direction.split(",").filter(Boolean));
    if (values.has(code)) values.delete(code); else values.add(code);
    update({ direction: [...values].sort().join(",") });
  }
  return { filters, params, update, toggleDirection, clear: () => setParams({}) };
}
