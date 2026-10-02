import { expect, it } from "vitest";
import { shouldRetryRead } from "./retry-policy.js";

it("never restarts a timed-out or cancelled read behind a loading indicator", () => {
  expect(shouldRetryRead(0, { code: "SNAPSHOT_TIMEOUT", status: 504 })).toBe(false);
  expect(shouldRetryRead(0, { name: "AbortError" })).toBe(false);
  expect(shouldRetryRead(0, { status: 404 })).toBe(false);
  expect(shouldRetryRead(0, { status: 503 })).toBe(true);
  expect(shouldRetryRead(1, { status: 503 })).toBe(false);
});
