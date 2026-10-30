/// <reference lib="webworker" />
import { env, pipeline, type FeatureExtractionPipeline } from "@huggingface/transformers";
import model from "../../model.json";
import wasmUrl from "../../node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.asyncify.wasm?url";
import wasmModuleUrl from "../../node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.asyncify.mjs?url";
import type { EmbeddedBatch, EmbeddingStatus, Precision } from "./embedding";

type Request =
  | { kind: "init"; requestId: string; precision: Precision }
  | { kind: "embed"; requestId: string; texts: string[]; batchSize: number };

let extractor: FeatureExtractionPipeline | null = null;
let status: EmbeddingStatus | null = null;

env.useBrowserCache = true;
env.allowLocalModels = true;
env.allowRemoteModels = false;
env.localModelPath = `/models/${model.revision}/`;
const wasm = env.backends.onnx.wasm;
if (wasm) {
  wasm.numThreads = self.crossOriginIsolated ? Math.min(4, Math.max(1, self.navigator.hardwareConcurrency || 2)) : 1;
  wasm.wasmPaths = { wasm: wasmUrl, mjs: wasmModuleUrl };
}

self.onmessage = (event: MessageEvent<Request>) => {
  void handle(event.data);
};

async function handle(request: Request) {
  try {
    const value = request.kind === "init"
      ? await initialize(request.precision, request.requestId)
      : await embed(request.texts, request.batchSize, request.requestId);
    self.postMessage({ requestId: request.requestId, value });
  } catch (error) {
    self.postMessage({ requestId: request.requestId, error: error instanceof Error ? error.message : String(error) });
  }
}

async function initialize(precision: Precision, requestId: string): Promise<EmbeddingStatus> {
  const requestedDtype = precision === "int8" ? "q8" : precision;
  const autoMatch = status && precision === "auto" && status.dtype === (status.backend === "WebGPU" ? "fp16" : "q8");
  if (status && (autoMatch || status.dtype === requestedDtype)) return status;
  await dispose();
  status = null;
  const started = performance.now();
  let fallbackReason: string | undefined;
  const gpuRequested = precision === "auto" || precision === "fp16";
  if (gpuRequested) {
    try {
      const adapter = await self.navigator.gpu?.requestAdapter();
      if (!adapter) throw new Error("WebGPU adapter unavailable");
      await load("webgpu", "fp16", requestId);
      const candidate = await infer(["EdgeSeek WebGPU runtime verification"]);
      validate(candidate[0]);
      status = {
        backend: "WebGPU", dtype: "fp16", dimension: model.dimension,
        modelId: model.id, modelKey: model.modelKey, initMs: performance.now() - started,
      };
      return status;
    } catch (error) {
      fallbackReason = error instanceof Error ? error.message : String(error);
      await dispose();
    }
  }

  const dtype = precision === "fp32" ? "fp32" : "q8";
  await load("wasm", dtype, requestId);
  const candidate = await infer(["EdgeSeek WASM runtime verification"]);
  validate(candidate[0]);
  status = {
    backend: "WASM", dtype, dimension: model.dimension,
    modelId: model.id, modelKey: model.modelKey, initMs: performance.now() - started,
    fallbackReason,
  };
  return status;
}

async function load(device: "wasm" | "webgpu", dtype: "fp32" | "q8" | "fp16", requestId: string) {
  const onProgress = (event: { status?: string; file?: string; loaded?: number; total?: number; progress?: number }) => {
    self.postMessage({ requestId, progress: { ...event, phase: "model-load" } });
  };
  extractor = await pipeline("feature-extraction", model.id, {
    revision: model.revision,
    device,
    dtype,
    progress_callback: onProgress,
  });
}

async function infer(texts: string[]) {
  if (!extractor) throw new Error("Embedding model is not loaded");
  const output = await extractor(texts, { pooling: "mean", normalize: model.normalize });
  const rows = output.tolist() as number[][];
  if (!Array.isArray(rows) || rows.length !== texts.length) throw new Error("Embedding output has an unexpected batch shape");
  rows.forEach(validate);
  return rows;
}

async function embed(texts: string[], requestedBatchSize: number, requestId: string): Promise<EmbeddedBatch> {
  if (!status || !extractor) throw new Error("Initialize the local model before embedding");
  if (!texts.length || texts.some((text) => !text.trim())) throw new Error("Embedding input cannot be empty");
  const batchSize = [1, 4, 8].includes(requestedBatchSize) ? requestedBatchSize : 4;
  const started = performance.now();
  const embeddings: number[][] = [];
  for (let offset = 0; offset < texts.length; offset += batchSize) {
    try {
      embeddings.push(...await infer(texts.slice(offset, offset + batchSize)));
    } catch (error) {
      if (status.backend !== "WebGPU") throw error;
      const fallbackReason = error instanceof Error ? error.message : String(error);
      await dispose();
      await load("wasm", "q8", requestId);
      const probe = await infer(["EdgeSeek WASM fallback verification"]);
      validate(probe[0]);
      status = { ...status, backend: "WASM", dtype: "q8", fallbackReason };
      embeddings.push(...await infer(texts.slice(offset, offset + batchSize)));
    }
    self.postMessage({ requestId, progress: { phase: "embedding", completed: Math.min(offset + batchSize, texts.length), total: texts.length } });
  }
  return { embeddings, elapsedMs: performance.now() - started, batchSize, backend: status.backend, dtype: status.dtype };
}

function validate(vector: number[]) {
  if (!Array.isArray(vector) || vector.length !== model.dimension || vector.some((n) => !Number.isFinite(n))) {
    throw new Error(`Expected ${model.dimension} finite embedding values`);
  }
  const norm = Math.sqrt(vector.reduce((sum, value) => sum + value * value, 0));
  if (Math.abs(norm - 1) > 0.02) throw new Error(`Embedding normalization check failed (norm=${norm.toFixed(5)})`);
}

async function dispose() {
  if (extractor && "dispose" in extractor && typeof extractor.dispose === "function") await extractor.dispose();
  extractor = null;
}
