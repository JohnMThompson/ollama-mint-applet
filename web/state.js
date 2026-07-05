export const STORAGE_KEY = "local-mistral-chat-state-v1";
export const STATE_SCHEMA_VERSION = 2;

const DEFAULT_SETTINGS = Object.freeze({
  model: "mistral",
  systemPrompt: "",
  temperature: 0.7,
  contextMessages: 16,
});

function finiteNumber(value, fallback) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function boundedNumber(value, fallback, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, finiteNumber(value, fallback)));
}

function normalizedSettings(settings) {
  const source = settings && typeof settings === "object" ? settings : {};
  return {
    model:
      typeof source.model === "string" && source.model.trim()
        ? source.model.trim().slice(0, 200)
        : DEFAULT_SETTINGS.model,
    systemPrompt:
      typeof source.systemPrompt === "string"
        ? source.systemPrompt.slice(0, 100_000)
        : DEFAULT_SETTINGS.systemPrompt,
    temperature: boundedNumber(source.temperature, DEFAULT_SETTINGS.temperature, 0, 2),
    contextMessages: Math.round(
      boundedNumber(source.contextMessages, DEFAULT_SETTINGS.contextMessages, 2, 40),
    ),
  };
}

function normalizedMessages(messages, fallbackTimestamp) {
  if (!Array.isArray(messages)) return [];
  return messages.flatMap((message) => {
    if (
      !message ||
      typeof message !== "object" ||
      !["user", "assistant"].includes(message.role) ||
      typeof message.content !== "string" ||
      !message.content.trim()
    ) {
      return [];
    }
    return [
      {
        role: message.role,
        content: message.content,
        createdAt: finiteNumber(message.createdAt, fallbackTimestamp),
      },
    ];
  });
}

export function emptyState() {
  return {
    schemaVersion: STATE_SCHEMA_VERSION,
    chats: [],
    activeChatId: null,
  };
}

export function normalizePersistedState(value, options = {}) {
  if (!value || typeof value !== "object" || !Array.isArray(value.chats)) {
    return emptyState();
  }
  const now = options.now ?? Date.now();
  const createId =
    options.createId ??
    (() => globalThis.crypto?.randomUUID?.() ?? `recovered-${now}-${Math.random()}`);
  const usedIds = new Set();
  const chats = value.chats.flatMap((chat) => {
    if (!chat || typeof chat !== "object") return [];
    let id = typeof chat.id === "string" && chat.id.trim() ? chat.id.trim() : createId();
    while (usedIds.has(id)) id = createId();
    usedIds.add(id);
    const createdAt = finiteNumber(chat.createdAt, now);
    const title =
      typeof chat.title === "string" && chat.title.trim()
        ? chat.title.replace(/\s+/g, " ").trim().slice(0, 80)
        : "New chat";
    const normalized = {
      id,
      title,
      createdAt,
      updatedAt: finiteNumber(chat.updatedAt, createdAt),
      messages: normalizedMessages(chat.messages, createdAt),
      settings: normalizedSettings(chat.settings),
    };
    if (typeof chat.sourceHandoffId === "string" && chat.sourceHandoffId) {
      normalized.sourceHandoffId = chat.sourceHandoffId.slice(0, 64);
    }
    return [normalized];
  });
  const requestedActiveId =
    typeof value.activeChatId === "string" ? value.activeChatId : null;
  return {
    schemaVersion: STATE_SCHEMA_VERSION,
    chats,
    activeChatId: chats.some((chat) => chat.id === requestedActiveId)
      ? requestedActiveId
      : chats[0]?.id ?? null,
  };
}

export function loadPersistedState(storage, options = {}) {
  let serialized;
  try {
    serialized = storage.getItem(STORAGE_KEY);
  } catch (error) {
    options.onError?.(error);
    return emptyState();
  }
  if (serialized === null) return emptyState();
  try {
    return normalizePersistedState(JSON.parse(serialized), options);
  } catch {
    try {
      storage.removeItem(STORAGE_KEY);
    } catch (error) {
      options.onError?.(error);
    }
    return emptyState();
  }
}

export function createStatePersistence(storage, onError = () => {}) {
  let errorReported = false;
  const reportError = (error) => {
    if (errorReported) return;
    errorReported = true;
    onError(error);
  };
  return {
    reportError,
    save(state) {
      try {
        storage.setItem(STORAGE_KEY, JSON.stringify(state));
        return true;
      } catch (error) {
        reportError(error);
        return false;
      }
    },
  };
}
