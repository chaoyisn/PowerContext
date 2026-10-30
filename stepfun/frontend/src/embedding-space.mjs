export function embeddingSpace(base, revision, backend, dtype) {
  if (!((backend === "WASM" && ["q8", "fp32"].includes(dtype)) || (backend === "WebGPU" && dtype === "fp16"))) return "";
  return `${base}:transformers=4.3.2:tokenizer=${revision}:dtype=${dtype}:backend=${backend}`;
}
