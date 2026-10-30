import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { mkdir, rename, rm, stat } from "node:fs/promises";
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const model = JSON.parse(await (await import("node:fs/promises")).readFile(join(root, "model.json"), "utf8"));
const files = [
  ["config.json", 650, "sha1", "72147e4ff4426ebedbfa2146c4a0999def51a313"],
  ["special_tokens_map.json", 125, "sha1", "a8b3208c2884c4efb86e49300fdd3dc877220cdf"],
  ["tokenizer_config.json", 366, "sha1", "37fca74771bc76a8e01178ce3a6055a0995f8093"],
  ["tokenizer.json", 711661, "sha1", "c17ed520ed8438736732a54957a69306b8822215"],
  ["vocab.txt", 231508, "sha1", "fb140275c155a9c7c5a3b3e0e77a9e839594a938"],
  ["onnx/model.onnx", 90387606, "sha256", "759c3cd2b7fe7e93933ad23c4c9181b7396442a2ed746ec7c1d46192c469c46e"],
  ["onnx/model_fp16.onnx", 45297825, "sha256", "2cdb5e58291813b6d6e248ed69010100246821a367fa17b1b81ae9483744533d"],
  ["onnx/model_quantized.onnx", 22972370, "sha256", "afdb6f1a0e45b715d0bb9b11772f032c399babd23bfc31fed1c170afc848bdb1"],
];
const destination = join(root, "frontend", "public", "models", model.revision, model.id);
const evidence = join(root, "benchmark", "results", "v2", "model-manifest.json");
await mkdir(destination, { recursive: true });
const manifest = { model: model.id, revision: model.revision, license: "Apache-2.0", source: `https://huggingface.co/${model.id}/tree/${model.revision}`, files: [] };

for (const [name, bytes, algorithm, expected] of files) {
  const path = join(destination, name);
  await mkdir(dirname(path), { recursive: true });
  if (!await verified(path, bytes, algorithm, expected)) {
    const part = `${path}.part`;
    await rm(part, { force: true });
    const url = `https://huggingface.co/${model.id}/resolve/${model.revision}/${name}?download=true`;
    await download(url, part);
    if (!await verified(part, bytes, algorithm, expected)) {
      const actual = await digest(part, algorithm);
      await rm(part, { force: true });
      throw new Error(`${name}: integrity check failed (expected ${algorithm}:${expected}, got ${actual})`);
    }
    await rename(part, path);
  }
  manifest.files.push({ path: name, bytes, integrity: `${algorithm}:${expected}` });
  console.log(`verified ${name} (${bytes} bytes)`);
}

await mkdir(dirname(evidence), { recursive: true });
await (await import("node:fs/promises")).writeFile(evidence, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`manifest: ${evidence}`);

async function verified(path, expectedBytes, algorithm, expectedHash) {
  try {
    if ((await stat(path)).size !== expectedBytes) return false;
    return await digest(path, algorithm) === expectedHash;
  } catch { return false; }
}

async function digest(path, algorithm) {
  const hash = createHash(algorithm);
  if (algorithm === "sha1") {
    const size = (await stat(path)).size;
    hash.update(`blob ${size}\0`);
  }
  for await (const chunk of createReadStream(path)) hash.update(chunk);
  return hash.digest("hex");
}

function download(url, output) {
  return new Promise((resolve, reject) => {
    const child = spawn("curl", ["--fail", "--location", "--retry", "3", "--retry-delay", "1", "--silent", "--show-error", "--output", output, url], { stdio: "inherit" });
    child.once("error", reject);
    child.once("exit", (code) => code === 0 ? resolve() : reject(new Error(`curl exited ${code} while downloading ${url}`)));
  });
}
