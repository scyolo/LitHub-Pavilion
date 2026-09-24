import { useQuery } from "@tanstack/react-query";
import { api } from "../api.js";

export function useCrawlStatus() {
  return useQuery({
    queryKey: ["crawl-status"],
    queryFn: ({ signal }) => api.crawlStatus(signal),
    refetchInterval: api.isSnapshot ? false : (query) => query.state.data?.running ? 3000 : 60000,
    refetchIntervalInBackground: false,
  });
}

export function useDashboard(filters = {}) {
  return useQuery({
    queryKey: ["dashboard", filters],
    queryFn: ({ signal }) => api.dashboard(filters, signal),
    refetchInterval: api.isSnapshot ? false : 30000,
    refetchIntervalInBackground: false,
  });
}
