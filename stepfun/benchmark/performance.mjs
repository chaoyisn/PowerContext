export function compressionRatio(originalBytes, quantizedBytes) {
  if (typeof originalBytes !== "number" || typeof quantizedBytes !== "number" || !Number.isFinite(originalBytes) || !Number.isFinite(quantizedBytes) || originalBytes <= 0 || quantizedBytes <= 0) return null;
  return Number((originalBytes / quantizedBytes).toFixed(3));
}
