import assert from "node:assert/strict";
import test from "node:test";

import { readStream } from "../web/stream.js";


function bodyFromChunks(chunks) {
  let index = 0;
  return {
    getReader() {
      return {
        async read() {
          if (index === chunks.length) return { done: true };
          return { done: false, value: chunks[index++] };
        },
      };
    },
  };
}


test("processes terminated and unterminated final records", async () => {
  const encoder = new TextEncoder();
  const body = bodyFromChunks([
    encoder.encode('{"message":{"content":"first"}}\n'),
    encoder.encode('{"message":{"content":"second"}}'),
  ]);
  const tokens = [];

  await readStream(body, (token) => tokens.push(token));

  assert.deepEqual(tokens, ["first", "second"]);
});


test("handles records split across arbitrary chunk boundaries", async () => {
  const encoder = new TextEncoder();
  const encoded = encoder.encode('{"message":{"content":"complete"}}\n');
  const body = bodyFromChunks([encoded.slice(0, 4), encoded.slice(4, 17), encoded.slice(17)]);
  const tokens = [];

  await readStream(body, (token) => tokens.push(token));

  assert.deepEqual(tokens, ["complete"]);
});


test("flushes split Unicode sequences", async () => {
  const encoder = new TextEncoder();
  const encoded = encoder.encode('{"message":{"content":"café 🍵"}}');
  const split = encoded.indexOf(0xf0) + 2;
  const body = bodyFromChunks([encoded.slice(0, split), encoded.slice(split)]);
  const tokens = [];

  await readStream(body, (token) => tokens.push(token));

  assert.deepEqual(tokens, ["café 🍵"]);
});


test("propagates final error records", async () => {
  const body = bodyFromChunks([new TextEncoder().encode('{"error":"failed"}')]);

  await assert.rejects(readStream(body, () => {}), /failed/);
});
