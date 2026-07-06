import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";


const source = await readFile(
  new URL("../cinnamon/local-mistral-chat@local/appletStream.js", import.meta.url),
  "utf8",
);
const context = vm.createContext({ JSON, Error });
vm.runInContext(source, context);
const NdjsonStreamParser = context.NdjsonStreamParser;


test("applet parser handles records split across chunks", () => {
  const tokens = [];
  const parser = new NdjsonStreamParser((token) => tokens.push(token));

  parser.push('{"message":{"cont');
  parser.push('ent":"first"}}\n{"message":');
  parser.push('{"content":"second"}}\n');
  parser.finish();

  assert.deepEqual(tokens, ["first", "second"]);
});


test("applet parser flushes an unterminated final record", () => {
  const tokens = [];
  const parser = new NdjsonStreamParser((token) => tokens.push(token));

  parser.push('{"message":{"content":"final"}}');
  parser.finish();

  assert.deepEqual(tokens, ["final"]);
});


test("applet parser preserves Unicode content", () => {
  const tokens = [];
  const parser = new NdjsonStreamParser((token) => tokens.push(token));

  parser.push('{"message":{"content":"café 🍵"}}\n');

  assert.deepEqual(tokens, ["café 🍵"]);
});


test("applet parser reports server and malformed-record errors", () => {
  const serverError = new NdjsonStreamParser(() => {});
  assert.throws(() => serverError.push('{"error":"failed"}\n'), /failed/);

  const malformed = new NdjsonStreamParser(() => {});
  assert.throws(() => malformed.push("not-json\n"), /Invalid streaming response/);
});
