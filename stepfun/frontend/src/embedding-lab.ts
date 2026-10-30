import model from "../../model.json";
import { EmbeddingClient, type Precision } from "./embedding";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const status = $("status");
const progress = $("progress") as HTMLProgressElement;
const output = $("output");
const errors = $("errors");
const runButton = $("run") as HTMLButtonElement;
const downloadButton = $("download") as HTMLButtonElement;
const precision = $("precision") as HTMLSelectElement;
const history: Record<string, unknown>[] = [];
let latest: Record<string, unknown> | null = null;
$("model").textContent = `${model.id} · revision ${model.revision} · mean pooling · normalized · ${model.dimension} dimensions`;

runButton.onclick = async () => {
  runButton.disabled = true;
  downloadButton.disabled = true;
  output.textContent = "";
  errors.textContent = "[]";
  const log: Record<string, unknown>[] = [];
  const client = new EmbeddingClient();
  const started = performance.now();
  const timeout = setTimeout(() => client.close(), 120_000);
  client.onProgress = (event) => {
    log.push({ at: Number((performance.now() - started).toFixed(2)), ...event });
    status.textContent = `${String(event.phase)} · ${String(event.file ?? event.status ?? "")}`;
    if (typeof event.progress === "number") progress.value = event.progress / 100;
    if (typeof event.loaded === "number" && typeof event.total === "number" && event.total > 0) progress.value = event.loaded / event.total;
    progress.hidden = false;
  };

  try {
    const requestedPrecision = precision.value as Precision;
    const init = await withTimeout(client.initialize(requestedPrecision), 120_000, "Model initialization timed out");
    status.textContent = `${init.backend} · ${init.dtype} ready · ${init.initMs.toFixed(1)} ms`;
    const a = ($( "text-a") as HTMLTextAreaElement).value;
    const b = ($( "text-b") as HTMLTextAreaElement).value;
    const run = await withTimeout(client.embed([a, b, a], 1), 60_000, "Inference timed out");
    const [va, vb, vaRepeat] = run.embeddings;
    const norms = run.embeddings.map(norm);
    const difference = distance(va, vb);
    const repeatDifference = distance(va, vaRepeat);
    latest = {
      format: "edgeseek-v2-browser-run-1",
      at: new Date().toISOString(), browser: navigator.userAgent,
      model: model.id, revision: model.revision, modelKey: model.modelKey,
      requestedPrecision, backend: run.backend, dtype: run.dtype, device: run.backend === "WASM" ? "wasm" : "webgpu",
      pooling: model.pooling, normalize: model.normalize, dimension: model.dimension,
      texts: [a, b], vectors: await Promise.all(run.embeddings.map(async (vector) => ({ dimension: vector.length, norm: norm(vector), finite: vector.every(Number.isFinite), sha256: await hash(vector) }))),
      normRange: [Math.min(...norms), Math.max(...norms)], differentInputL2: difference, repeatInputL2: repeatDifference,
      initMs: init.initMs, inferenceMs: run.elapsedMs, endToEndMs: performance.now() - started,
      vectorizationExecutedIn: "browser module worker", modelAssets: log.filter((row) => row.phase === "model-load"), progressLog: log, errors: [],
    };
    localStorage.setItem("edgeseek.v2.lab.last-run", JSON.stringify(latest));
    output.textContent = JSON.stringify(latest, null, 2);
    status.textContent = `${run.backend} · ${run.dtype} · 3 vectors · ${run.elapsedMs.toFixed(1)} ms`;
    downloadButton.disabled = false;
  } catch (error) {
    const raw = error instanceof Error ? { name: error.name, message: error.message, stack: error.stack } : { message: String(error) };
    const record = { at: new Date().toISOString(), category: classify(raw.message), raw, userAgent: navigator.userAgent, reproduction: "Open /embedding-lab.html, select one precision, click Load model and embed." };
    history.push(record);
    errors.textContent = JSON.stringify(history, null, 2);
    console.error("EdgeSeek V2 browser lab failure", record);
    status.textContent = `FAILED · ${record.category}`;
    output.textContent = JSON.stringify(record, null, 2);
    latest = { format: "edgeseek-v2-browser-run-1", ...record, model: model.id, revision: model.revision };
    downloadButton.disabled = false;
  } finally {
    clearTimeout(timeout);
    client.close();
    progress.hidden = true;
    runButton.disabled = false;
  }
};

downloadButton.onclick = () => {
  if (!latest) return;
  const blob = new Blob([JSON.stringify(latest, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `edgeseek-v2-${new Date().toISOString().replaceAll(":", "-")}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 0);
};

function classify(message: string): string {
  if (/network|fetch|failed to fetch|ERR_|timeout/i.test(message)) return "NETWORK";
  if (/404|not found|asset|\.onnx|\.json|\.wasm/i.test(message)) return "ASSET";
  if (/worker|module script/i.test(message)) return "WORKER";
  if (/transformers|pipeline|model/i.test(message)) return "TRANSFORMERS";
  if (/onnx|session|execution provider/i.test(message)) return "ONNX_RUNTIME";
  if (/unsupported|shape|operator|dimension/i.test(message)) return "MODEL_COMPATIBILITY";
  if (/out of memory|memory|allocation|oom/i.test(message)) return "RESOURCE_OOM";
  if (/webgpu|adapter|device|gpu/i.test(message)) return "GPU_INITIALIZATION";
  return "UNKNOWN";
}

function norm(vector: number[]) { return Math.sqrt(vector.reduce((sum, value) => sum + value * value, 0)); }
function distance(a: number[], b: number[]) { return Math.sqrt(a.reduce((sum, value, index) => sum + (value - b[index]) ** 2, 0)); }
async function hash(vector: number[]) { return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(vector))))).map((byte) => byte.toString(16).padStart(2, "0")).join(""); }
function withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  return Promise.race([promise, new Promise<never>((_, reject) => setTimeout(() => reject(new Error(message)), ms))]);
}
