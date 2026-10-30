export type KnowledgeBase = {
  id: string;
  name: string;
  modelKey: string;
  dimension: number;
  documentCount: number;
  createdAt: string;
};

export type StoredDocument = {
  id: string;
  filename: string;
  sha256: string;
  chunkCount: number;
  status: string;
  createdAt: string;
  content: string;
};

export type SearchResult = {
  id: string;
  document: string;
  metadata: Record<string, string | number | boolean | null> | null;
  score: number | null;
};

export async function api<T>(url: string, init?: RequestInit): Promise<{ data: T; requestMs: number; timings: { outboundMs?: number; serverMs?: number; inboundHeadersMs?: number; inboundBodyParsedMs?: number } }> {
  const start = performance.now();
  const clientStart = performance.timeOrigin + start;
  const response = await fetch(url, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  const requestMs = performance.now() - start;
  const headersAt = performance.timeOrigin + performance.now();
  const body = await response.json() as T & { error?: string };
  const bodyAt = performance.timeOrigin + performance.now();
  const receivedHeader = response.headers.get("x-edgeseek-server-received");
  const sentHeader = response.headers.get("x-edgeseek-server-sent");
  const received = receivedHeader === null ? NaN : Number(receivedHeader);
  const sent = sentHeader === null ? NaN : Number(sentHeader);
  if (!response.ok) throw new Error(body.error ?? `API returned HTTP ${response.status}`);
  return { data: body, requestMs, timings: {
    outboundMs: Number.isFinite(received) ? received - clientStart : undefined,
    serverMs: Number.isFinite(received) && Number.isFinite(sent) ? sent - received : undefined,
    inboundHeadersMs: Number.isFinite(sent) ? headersAt - sent : undefined,
    inboundBodyParsedMs: Number.isFinite(sent) ? bodyAt - sent : undefined,
  } };
}

export function post<T>(url: string, value: unknown) {
  return api<T>(url, { method: "POST", body: JSON.stringify(value) });
}
