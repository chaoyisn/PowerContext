export function recallAtK(results, relevant, k = 5) {
  const expected = new Set(relevant);
  if (!expected.size) return 0;
  const found = new Set(results.slice(0, k).filter((item) => expected.has(item)).slice(0, expected.size));
  return found.size / expected.size;
}

export function meanReciprocalRank(ranks) {
  if (!ranks.length) return 0;
  return ranks.reduce((sum, rank) => sum + (rank > 0 ? 1 / rank : 0), 0) / ranks.length;
}
