import { expect, it } from "vitest";
import { expandTokens } from "./fuzzy-terms.js";

it("completes every query fragment with a bounded set of real title terms", () => {
  expect(expandTokens(["spec", "dec"], [["specul", 12], ["decod", 9]]))
    .toEqual([["spec", "specul"], ["dec", "decod"]]);
  const groups = expandTokens(["mach", "lea"], Array.from({ length: 30 }, (_, i) => ["mach" + i, i + 1]));
  expect(groups.every(group => group.length <= 4)).toBe(true);
  expect(expandTokens(["ai", "ml"], [["aid", 5], ["mlp", 5]])).toEqual([["ai"], ["ml"]]);
});
