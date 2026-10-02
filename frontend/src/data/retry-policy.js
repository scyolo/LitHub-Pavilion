// Keep per-page overrides and the shared QueryClient on the same bounded policy.
export function shouldRetryRead(attempt, error) {
  if (error?.code === "SNAPSHOT_TIMEOUT" || error?.name === "AbortError") return false;
  if (error?.status >= 400 && error.status < 500) return false;
  return attempt < 1;
}
