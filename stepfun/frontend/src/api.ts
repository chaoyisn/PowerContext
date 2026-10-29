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

export async function api<T>(url: string, init?: RequestInit): Promise<{ data: T; requestMs: number }> {
  const start = performance.now();
  const response = await fetch(url, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  const requestMs = performance.now() - start;
  const body = await response.json() as T & { error?: string };
  if (!response.ok) throw new Error(body.error ?? `API returned HTTP ${response.status}`);
  return { data: body, requestMs };
}

export function post<T>(url: string, value: unknown) {
  return api<T>(url, { method: "POST", body: JSON.stringify(value) });
}
