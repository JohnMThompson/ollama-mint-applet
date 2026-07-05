import assert from "node:assert/strict";
import test from "node:test";

import {
  createStatePersistence,
  loadPersistedState,
  normalizePersistedState,
  STATE_SCHEMA_VERSION,
  STORAGE_KEY,
} from "../web/state.js";


test("migrates and repairs legacy chat state", () => {
  let nextId = 0;
  const state = normalizePersistedState(
    {
      chats: [
        {
          title: "  Legacy   chat ",
          createdAt: "invalid",
          messages: [
            { role: "user", content: "Hello" },
            { role: "system", content: "discard me" },
            { role: "assistant", content: 42 },
          ],
          settings: {
            model: "",
            temperature: 99,
            contextMessages: -4,
          },
        },
        null,
      ],
      activeChatId: "missing",
    },
    { now: 1000, createId: () => `recovered-${++nextId}` },
  );

  assert.equal(state.schemaVersion, STATE_SCHEMA_VERSION);
  assert.equal(state.chats.length, 1);
  assert.equal(state.chats[0].id, "recovered-1");
  assert.equal(state.chats[0].title, "Legacy chat");
  assert.deepEqual(state.chats[0].messages, [
    { role: "user", content: "Hello", createdAt: 1000 },
  ]);
  assert.deepEqual(state.chats[0].settings, {
    model: "mistral",
    systemPrompt: "",
    temperature: 2,
    contextMessages: 2,
  });
  assert.equal(state.activeChatId, "recovered-1");
});


test("repairs duplicate IDs and invalid active chat references", () => {
  let nextId = 0;
  const state = normalizePersistedState(
    {
      chats: [
        { id: "same", messages: [], settings: {} },
        { id: "same", messages: [], settings: {} },
      ],
      activeChatId: "unknown",
    },
    { now: 1000, createId: () => `replacement-${++nextId}` },
  );

  assert.deepEqual(
    state.chats.map((chat) => chat.id),
    ["same", "replacement-1"],
  );
  assert.equal(state.activeChatId, "same");
});


test("removes malformed serialized state", () => {
  const removed = [];
  const storage = {
    getItem: () => "{invalid",
    removeItem: (key) => removed.push(key),
  };

  const state = loadPersistedState(storage);

  assert.deepEqual(state.chats, []);
  assert.deepEqual(removed, [STORAGE_KEY]);
});


test("replaces non-object state with an empty schema", () => {
  for (const value of [null, [], "text", { chats: "invalid" }]) {
    const state = normalizePersistedState(value);
    assert.equal(state.schemaVersion, STATE_SCHEMA_VERSION);
    assert.deepEqual(state.chats, []);
    assert.equal(state.activeChatId, null);
  }
});


test("persistence failures do not throw and notify only once", () => {
  let attempts = 0;
  const errors = [];
  const storage = {
    setItem() {
      attempts += 1;
      throw new DOMException("Quota exceeded", "QuotaExceededError");
    },
  };
  const persistence = createStatePersistence(storage, (error) => errors.push(error));

  assert.equal(persistence.save({ chats: [] }), false);
  assert.equal(persistence.save({ chats: [{ id: "still-in-memory" }] }), false);
  assert.equal(attempts, 2);
  assert.equal(errors.length, 1);
  assert.equal(errors[0].name, "QuotaExceededError");
});


test("storage access failure returns usable state and reports once", () => {
  const errors = [];
  const storage = {
    getItem() {
      throw new DOMException("Blocked", "SecurityError");
    },
  };
  const persistence = createStatePersistence(storage, (error) => errors.push(error));

  const state = loadPersistedState(storage, {
    onError: persistence.reportError,
  });
  persistence.reportError(new Error("second failure"));

  assert.deepEqual(state.chats, []);
  assert.equal(errors.length, 1);
  assert.equal(errors[0].name, "SecurityError");
});
