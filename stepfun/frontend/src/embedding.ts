export type Precision = "auto" | "fp32" | "int8" | "fp16";
export type EmbeddingStatus = {
  backend: "WebGPU" | "WASM";
  dtype: "fp32" | "q8" | "fp16";
  dimension: number;
  modelId: string;
  modelKey: string;
  initMs: number;
  fallbackReason?: string;
};
export type EmbeddedBatch = {
  embeddings: number[][];
  elapsedMs: number;
  batchSize: number;
  backend: "WebGPU" | "WASM";
  dtype: "fp32" | "q8" | "fp16";
};

type Reply = { requestId: string; value?: unknown; error?: string; progress?: Record<string, unknown> };

export class EmbeddingClient {
  private worker: Worker;
  private sequence = 0;
  private pending = new Map<string, { resolve: (value: unknown) => void; reject: (error: Error) => void }>();
  onProgress?: (progress: Record<string, unknown>) => void;

  constructor() {
    this.worker = new Worker(new URL("./embedding-worker.ts", import.meta.url), { type: "module" });
    this.worker.onmessage = (event: MessageEvent<Reply>) => {
      const message = event.data;
      if (message.progress) {
        this.onProgress?.(message.progress);
        return;
      }
      const pending = this.pending.get(message.requestId);
      if (!pending) return;
      this.pending.delete(message.requestId);
      if (message.error) pending.reject(new Error(message.error));
      else pending.resolve(message.value);
    };
    this.worker.onerror = (event) => {
      for (const item of this.pending.values()) item.reject(new Error(event.message));
      this.pending.clear();
    };
  }

  initialize(precision: Precision) {
    return this.request<EmbeddingStatus>({ kind: "init", precision });
  }

  embed(texts: string[], batchSize: number) {
    return this.request<EmbeddedBatch>({ kind: "embed", texts, batchSize });
  }

  close() {
    this.worker.terminate();
    this.pending.clear();
  }

  private request<T>(payload: Record<string, unknown>): Promise<T> {
    const requestId = String(++this.sequence);
    return new Promise<T>((resolve, reject) => {
      this.pending.set(requestId, { resolve: (value) => resolve(value as T), reject });
      this.worker.postMessage({ ...payload, requestId });
    });
  }
}
