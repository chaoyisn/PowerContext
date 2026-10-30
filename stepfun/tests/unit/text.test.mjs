import assert from "node:assert/strict";
import test from "node:test";
import { chunkText, sha256Text } from "../../frontend/src/text-utils.mjs";

test("chunkText keeps bounded chunks with overlap and handles blank input", () => {
  const chunks = chunkText("abcdefghijklmnopqrstuvwxyz", 20, 5);
  assert.ok(chunks.length > 1);
  assert.ok(chunks.every((chunk) => chunk.length <= 20));
  assert.equal(chunks[0].slice(-5), chunks[1].slice(0, 5));
  assert.deepEqual(chunkText(" \n "), []);
});

test("sha256Text produces the standard SHA-256 digest", async () => {
  assert.equal(await sha256Text("hello"), "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824");
});
