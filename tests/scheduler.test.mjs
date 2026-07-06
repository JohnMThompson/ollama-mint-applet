import assert from "node:assert/strict";
import test from "node:test";

import { createDebouncedTask, createFrameScheduler } from "../web/scheduler.js";


test("coalesces many stream chunks into one animation frame", () => {
  let callbackCount = 0;
  let pendingFrame;
  const scheduler = createFrameScheduler(
    () => {
      callbackCount += 1;
    },
    {
      requestFrame(callback) {
        pendingFrame = callback;
        return 1;
      },
      cancelFrame() {},
    },
  );

  for (let index = 0; index < 100; index += 1) scheduler.schedule();
  assert.equal(callbackCount, 0);
  pendingFrame();
  assert.equal(callbackCount, 1);
});


test("debounces persistence and supports final flush", () => {
  let callbackCount = 0;
  let nextTimer = 0;
  const pending = new Map();
  const task = createDebouncedTask(
    () => {
      callbackCount += 1;
    },
    750,
    {
      setTimer(callback) {
        nextTimer += 1;
        pending.set(nextTimer, callback);
        return nextTimer;
      },
      clearTimer(timer) {
        pending.delete(timer);
      },
    },
  );

  for (let index = 0; index < 100; index += 1) task.schedule();
  assert.equal(pending.size, 1);
  assert.equal(callbackCount, 0);
  task.flush();
  assert.equal(pending.size, 0);
  assert.equal(callbackCount, 1);
});


test("cancels pending rendering and persistence", () => {
  const cancelled = [];
  const frame = createFrameScheduler(() => {}, {
    requestFrame: () => 42,
    cancelFrame: (id) => cancelled.push(id),
  });
  frame.schedule();
  frame.cancel();

  let persistenceRan = false;
  const persistence = createDebouncedTask(() => {
    persistenceRan = true;
  }, 750);
  persistence.schedule();
  persistence.cancel();

  assert.deepEqual(cancelled, [42]);
  assert.equal(persistenceRan, false);
});
