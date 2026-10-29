import { spawn } from "node:child_process";
import { resolve } from "node:path";

const children = [
  spawn(process.execPath, ["server/index.mjs"], { stdio: "inherit" }),
  spawn(process.execPath, [resolve("node_modules/vite/bin/vite.js"), "--host", "127.0.0.1"], { stdio: "inherit" }),
];
let stopping = false;

function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) if (child.exitCode === null) child.kill();
  if (code) process.exitCode = code;
}

for (const child of children) {
  child.on("error", (error) => { console.error(error.message); stop(1); });
  child.on("exit", (code) => { if (!stopping) stop(code || 0); });
}
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => stop());
