import { useQuery } from "@tanstack/react-query";
import { api } from "../api.js";

export function useCrawlStatus() {
  return useQuery({
    queryKey: ["crawl-status"],
    queryFn: ({ signal }) => api.crawlStatus(signal),
    refetchInterval: (query) => query.state.data?.running ? 3000 : 60000,
    refetchIntervalInBackground: false,
  });
}

export function useDashboard(filters = {}) {
  return useQuery({
    queryKey: ["dashboard", filters],
    queryFn: ({ signal }) => api.dashboard(filters, signal),
    refetchInterval: 30000,
    refetchIntervalInBackground: false,
  });
}
