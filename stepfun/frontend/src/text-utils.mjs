export function chunkText(input, maxChars = 850, overlap = 120) {
  const text = String(input).replace(/\r\n?/g, "\n").replace(/[ \t]+/g, " ").trim();
  if (!text) return [];
  const size = Math.max(1, Math.trunc(maxChars));
  const shared = Math.max(0, Math.min(Math.trunc(overlap), size - 1));
  const chunks = [];
  for (let start = 0; start < text.length;) {
    let end = Math.min(start + size, text.length);
    if (end < text.length) {
      const boundary = text.lastIndexOf(" ", end);
      if (boundary > start + Math.floor(size * 0.65)) end = boundary;
    }
    const value = text.slice(start, end).trim();
    if (value) chunks.push(value);
    if (end >= text.length) break;
    start = Math.max(start + 1, end - shared);
  }
  return chunks;
}

export async function sha256Text(text) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(bytes), (value) => value.toString(16).padStart(2, "0")).join("");
}
