import assert from "node:assert/strict";
import test from "node:test";
import { meanReciprocalRank, recallAtK } from "../../benchmark/quality.mjs";
import { compressionRatio } from "../../benchmark/performance.mjs";

test("recall@K and MRR measure labeled retrieval results", () => {
  assert.equal(recallAtK(["a", "b", "c"], ["b", "c"], 2), 0.5);
  assert.equal(recallAtK(["a", "b", "c"], ["b"], 2), 1);
  assert.equal(meanReciprocalRank([1, 0, 2]), 0.5);
});

test("compression ratio is calculated only from two measured positive sizes", () => {
  assert.equal(compressionRatio(90_400_000, 23_000_000), 3.93);
  assert.equal(compressionRatio(undefined, 23_000_000), null);
  assert.equal(compressionRatio(90_400_000, 0), null);
});
