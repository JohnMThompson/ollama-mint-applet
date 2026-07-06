export function createFrameScheduler(
  callback,
  {
    requestFrame = globalThis.requestAnimationFrame,
    cancelFrame = globalThis.cancelAnimationFrame,
  } = {},
) {
  let frame = null;
  return {
    schedule() {
      if (frame !== null) return;
      frame = requestFrame(() => {
        frame = null;
        callback();
      });
    },
    cancel() {
      if (frame === null) return;
      cancelFrame(frame);
      frame = null;
    },
  };
}

export function createDebouncedTask(
  callback,
  delay,
  {
    setTimer = globalThis.setTimeout,
    clearTimer = globalThis.clearTimeout,
  } = {},
) {
  let timer = null;
  return {
    schedule() {
      if (timer !== null) clearTimer(timer);
      timer = setTimer(() => {
        timer = null;
        callback();
      }, delay);
    },
    cancel() {
      if (timer === null) return;
      clearTimer(timer);
      timer = null;
    },
    flush() {
      if (timer === null) return;
      clearTimer(timer);
      timer = null;
      callback();
    },
  };
}
