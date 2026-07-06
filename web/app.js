import { readStream } from "./stream.js";
import { createDebouncedTask, createFrameScheduler } from "./scheduler.js";
import {
  createStatePersistence,
  enforceRetention,
  loadPersistedState,
  MAX_STORED_BYTES,
} from "./state.js";

const els = {
  chatList: document.querySelector("#chatList"),
  chatTitle: document.querySelector("#chatTitle"),
  clearHistoryButton: document.querySelector("#clearHistoryButton"),
  composer: document.querySelector("#composer"),
  connectionStatus: document.querySelector("#connectionStatus"),
  contextInput: document.querySelector("#contextInput"),
  generateTitlesInput: document.querySelector("#generateTitlesInput"),
  menuButton: document.querySelector("#menuButton"),
  messages: document.querySelector("#messages"),
  modelDialog: document.querySelector("#modelDialog"),
  modelDialogError: document.querySelector("#modelDialogError"),
  modelDialogForm: document.querySelector("#modelDialogForm"),
  modelSelect: document.querySelector("#modelSelect"),
  loadModelButton: document.querySelector("#loadModelButton"),
  loadModelSelect: document.querySelector("#loadModelSelect"),
  newChatButton: document.querySelector("#newChatButton"),
  promptInput: document.querySelector("#promptInput"),
  searchInput: document.querySelector("#searchInput"),
  sendButton: document.querySelector("#sendButton"),
  settingsButton: document.querySelector("#settingsButton"),
  settingsPanel: document.querySelector("#settingsPanel"),
  sidebar: document.querySelector("#sidebar"),
  stopButton: document.querySelector("#stopButton"),
  storageStatus: document.querySelector("#storageStatus"),
  systemPrompt: document.querySelector("#systemPrompt"),
  temperatureInput: document.querySelector("#temperatureInput"),
};

const persistence = createStatePersistence(localStorage, () => {
  queueMicrotask(() => {
    showToast(
      "Chat history could not be saved. This session remains available in memory; delete chats or use Clear history to free browser storage.",
    );
  });
});
let state = loadPersistedState(localStorage, {
  onError: persistence.reportError,
});
reportRetention(enforceRetention(state));
let abortController = null;
let titleAbortController = null;
let runningModels = [];

init();

async function init() {
  bindEvents();
  await importChatHandoff();
  render();
  await loadModels();
}

function bindEvents() {
  els.newChatButton.addEventListener("click", () => {
    createChat();
    closeMobileSidebar();
  });

  els.clearHistoryButton.addEventListener("click", () => {
    if (!state.chats.length || !confirm("Clear all chat history?")) return;
    state = { ...state, chats: [], activeChatId: null };
    createChat({ persistNow: false });
  });

  els.searchInput.addEventListener("input", renderChatList);
  els.settingsButton.addEventListener("click", () => {
    const expanded = els.settingsPanel.hidden;
    els.settingsPanel.hidden = !expanded;
    els.settingsButton.setAttribute("aria-expanded", String(expanded));
  });
  els.menuButton.addEventListener("click", () => {
    const expanded = els.sidebar.classList.toggle("open");
    els.menuButton.setAttribute("aria-expanded", String(expanded));
  });
  els.stopButton.addEventListener("click", stopGeneration);

  els.promptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      els.composer.requestSubmit();
    }
  });

  els.composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = els.promptInput.value.trim();
    if (!content || abortController) return;
    await sendMessage(content);
  });
  els.modelDialog.addEventListener("cancel", (event) => event.preventDefault());
  els.modelDialogForm.addEventListener("submit", loadSelectedModel);

  for (const input of [
    els.systemPrompt,
    els.temperatureInput,
    els.contextInput,
    els.generateTitlesInput,
    els.modelSelect,
  ]) {
    input.addEventListener("change", saveCurrentSettings);
  }
}

function saveState() {
  reportRetention(enforceRetention(state));
  persistence.save(state);
}

function reportRetention(report) {
  const usedKilobytes = Math.ceil(report.estimatedBytes / 1000);
  const limitMegabytes = (MAX_STORED_BYTES / 1_000_000).toFixed(0);
  els.storageStatus.textContent = `${usedKilobytes} KB of ${limitMegabytes} MB history`;
  const changes =
    report.truncatedMessages + report.removedMessages + report.removedChats;
  if (!changes) return;
  queueMicrotask(() => {
    showToast(
      `History limits applied: ${report.removedChats} chats removed, ${report.removedMessages} older messages removed, ${report.truncatedMessages} long messages truncated.`,
    );
  });
}

async function importChatHandoff() {
  const url = new URL(window.location.href);
  const handoffId = url.searchParams.get("handoff");
  if (!handoffId) return;

  url.searchParams.delete("handoff");
  history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);

  const existingChat = state.chats.find((chat) => chat.sourceHandoffId === handoffId);
  if (existingChat) {
    state.activeChatId = existingChat.id;
    return;
  }

  try {
    const response = await fetch(`/api/handoffs/${encodeURIComponent(handoffId)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Unable to transfer popup chat");

    const messages = (data.messages || [])
      .filter((message) => ["user", "assistant"].includes(message.role) && typeof message.content === "string")
      .map((message) => ({ ...message, createdAt: Date.now() }));
    if (!messages.length) throw new Error("Transferred chat has no messages");

    const firstUserMessage = messages.find((message) => message.role === "user")?.content || "";
    const now = Date.now();
    const chat = {
      id: crypto.randomUUID(),
      sourceHandoffId: handoffId,
      title: makeFallbackTitle(firstUserMessage),
      createdAt: now,
      updatedAt: now,
      messages,
      settings: {
        ...defaultSettings(),
        model: data.model || "mistral",
      },
    };
    state.chats.unshift(chat);
    state.activeChatId = chat.id;
    saveState();
  } catch (error) {
    showToast(error.message);
  }
}

async function loadModels() {
  try {
    const response = await fetch("/api/models");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Unable to load models");
    const names = data.models.map((model) => model.name).filter(Boolean);
    runningModels = data.runningModels || [];
    const preferred = data.activeModel || activeChat()?.settings?.model || data.defaultModel || "mistral";
    const selected = resolveModelName(preferred, names);
    const uniqueNames = [...new Set([selected, ...names])];
    els.modelSelect.replaceChildren(...uniqueNames.map((name) => new Option(name, name)));
    els.modelSelect.value = selected;
    const chat = activeChat();
    if (chat && chat.settings.model !== selected) {
      chat.settings.model = selected;
      saveState();
    }
    if (data.activeModel) {
      els.connectionStatus.textContent = `Using running model ${data.activeModel}`;
      closeModelDialog();
    } else {
      els.connectionStatus.textContent = names.length ? "No model running" : "No downloaded models";
      showModelDialog(names, selected);
    }
  } catch (error) {
    const selected = activeChat()?.settings?.model || "mistral";
    els.modelSelect.replaceChildren(new Option(selected, selected));
    els.modelSelect.value = selected;
    els.connectionStatus.textContent = error.message;
    showToast(error.message);
  }
}

function showModelDialog(names, preferred) {
  els.loadModelSelect.replaceChildren(...names.map((name) => new Option(name, name)));
  els.loadModelSelect.value = resolveModelName(preferred, names);
  els.loadModelButton.disabled = names.length === 0;
  els.loadModelButton.textContent = "Load model";
  els.modelDialogError.hidden = true;
  els.modelDialogError.textContent = "";
  if (!els.modelDialog.open) els.modelDialog.showModal();
}

function closeModelDialog() {
  if (els.modelDialog.open) els.modelDialog.close();
}

async function loadSelectedModel(event) {
  event.preventDefault();
  const model = els.loadModelSelect.value;
  if (!model) return;

  els.loadModelButton.disabled = true;
  els.loadModelButton.textContent = "Loading…";
  els.modelDialogError.hidden = true;
  try {
    const response = await fetch("/api/models/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Unable to load model");
    runningModels = data.runningModels || [model];
    selectModel(model);
    els.connectionStatus.textContent = `Using running model ${model}`;
    closeModelDialog();
  } catch (error) {
    els.modelDialogError.textContent = error.message;
    els.modelDialogError.hidden = false;
  } finally {
    els.loadModelButton.disabled = false;
    els.loadModelButton.textContent = "Load model";
  }
}

function selectModel(model) {
  els.modelSelect.value = model;
  const chat = activeChat();
  if (chat) {
    chat.settings.model = model;
    saveState();
  }
}

function resolveModelName(preferred, names) {
  if (names.includes(preferred)) return preferred;
  return names.find((name) => name === `${preferred}:latest` || name.startsWith(`${preferred}:`)) || preferred;
}

function createChat({ persistNow = true } = {}) {
  const chat = {
    id: crypto.randomUUID(),
    title: "New chat",
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messages: [],
    settings: defaultSettings(),
  };
  state.chats.unshift(chat);
  state.activeChatId = chat.id;
  if (persistNow) saveState();
  render();
}

function defaultSettings() {
  return {
    model: els.modelSelect.value || "mistral",
    systemPrompt: "",
    temperature: 0.7,
    contextMessages: 16,
    generateTitles: false,
  };
}

function activeChat() {
  return state.chats.find((chat) => chat.id === state.activeChatId) || null;
}

function ensureActiveChat() {
  if (!activeChat()) createChat({ persistNow: false });
  return activeChat();
}

function render() {
  const chat = ensureActiveChat();
  els.chatTitle.textContent = chat.title;
  els.systemPrompt.value = chat.settings.systemPrompt || "";
  els.temperatureInput.value = chat.settings.temperature ?? 0.7;
  els.contextInput.value = chat.settings.contextMessages ?? 16;
  els.generateTitlesInput.checked = chat.settings.generateTitles === true;
  if (chat.settings.model) els.modelSelect.value = chat.settings.model;
  renderChatList();
  renderMessages();
  saveState();
}

function renderChatList() {
  const term = els.searchInput.value.trim().toLowerCase();
  const chats = state.chats.filter((chat) => chat.title.toLowerCase().includes(term));
  els.chatList.replaceChildren(...chats.map(renderChatItem));
}

function renderChatItem(chat) {
  const item = document.createElement("div");
  item.className = `chat-item${chat.id === state.activeChatId ? " active" : ""}`;
  const openChat = () => {
    state.activeChatId = chat.id;
    render();
    closeMobileSidebar();
  };

  const label = document.createElement("span");
  label.className = "chat-item-title";
  label.textContent = chat.title;

  const meta = document.createElement("span");
  meta.className = "chat-item-time";
  meta.textContent = formatDate(chat.updatedAt);

  const text = document.createElement("span");
  text.className = "chat-item-text";
  text.append(label, meta);

  const open = document.createElement("button");
  open.type = "button";
  open.className = "open-chat";
  open.setAttribute("aria-label", `Open chat: ${chat.title}`);
  if (chat.id === state.activeChatId) open.setAttribute("aria-current", "page");
  open.append(text);
  open.addEventListener("click", openChat);

  const del = document.createElement("button");
  del.type = "button";
  del.className = "delete-chat";
  del.textContent = "×";
  del.title = "Delete chat";
  del.setAttribute("aria-label", `Delete chat: ${chat.title}`);
  del.addEventListener("click", () => deleteChat(chat.id));

  const rename = document.createElement("button");
  rename.type = "button";
  rename.className = "rename-chat";
  rename.textContent = "✎";
  rename.title = "Rename chat";
  rename.setAttribute("aria-label", `Rename chat: ${chat.title}`);
  rename.addEventListener("click", () => renameChat(chat.id));

  const actions = document.createElement("span");
  actions.className = "chat-item-actions";
  actions.append(rename, del);

  item.append(open, actions);
  return item;
}

function renderMessages() {
  const chat = activeChat();
  if (!chat || chat.messages.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = "<div><h1>Local LLM Chat</h1><p>Ask a question, draft something, or continue a saved conversation.</p></div>";
    els.messages.replaceChildren(empty);
    return;
  }

  const thread = document.createElement("div");
  thread.className = "thread";
  for (const message of chat.messages) {
    thread.append(renderMessage(message));
  }
  els.messages.replaceChildren(thread);
  scrollToBottom();
}

function renderMessage(message) {
  const row = document.createElement("article");
  row.className = `message ${message.role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = message.role === "assistant" ? "M" : "You";

  const content = document.createElement("div");
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = renderMarkdown(message.content || "");
  content.append(bubble);

  if (message.content) {
    const actions = document.createElement("div");
    actions.className = "message-actions";
    const copy = document.createElement("button");
    copy.className = "copy-button";
    copy.type = "button";
    copy.textContent = "Copy";
    copy.addEventListener("click", async () => {
      await navigator.clipboard.writeText(message.content);
      copy.textContent = "Copied";
      setTimeout(() => (copy.textContent = "Copy"), 1200);
    });
    actions.append(copy);
    content.append(actions);
  }

  row.append(avatar, content);
  return row;
}

async function sendMessage(content) {
  if (!runningModels.length) {
    await loadModels();
    if (!runningModels.length) return;
  }
  const chat = ensureActiveChat();
  titleAbortController?.abort();
  titleAbortController = null;
  const userMessage = { role: "user", content, createdAt: Date.now() };
  const assistantMessage = { role: "assistant", content: "", createdAt: Date.now() };
  chat.messages.push(userMessage, assistantMessage);
  chat.updatedAt = Date.now();
  els.promptInput.value = "";
  setGenerating(true);
  render();

  abortController = new AbortController();
  const assistantBubbles = els.messages.querySelectorAll(".message.assistant .bubble");
  const activeBubble = assistantBubbles[assistantBubbles.length - 1];
  const streamedRender = createFrameScheduler(() => {
    if (!activeBubble?.isConnected) return;
    activeBubble.innerHTML = renderMarkdown(assistantMessage.content);
    scrollToBottom();
  });
  const streamedPersistence = createDebouncedTask(saveState, 750);
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildRequest(chat)),
      signal: abortController.signal,
    });
    if (!response.ok || !response.body) throw new Error(`Chat request failed (${response.status})`);
    await readStream(response.body, (chunk) => {
      assistantMessage.content += chunk;
      chat.updatedAt = Date.now();
      streamedRender.schedule();
      streamedPersistence.schedule();
    });
  } catch (error) {
    if (error.name !== "AbortError") {
      assistantMessage.content += `\n\nError: ${error.message}`;
      showToast(error.message);
    }
  } finally {
    streamedRender.cancel();
    streamedPersistence.cancel();
    abortController = null;
    setGenerating(false);
    chat.updatedAt = Date.now();
    render();
    if (chat.title === "New chat" && assistantMessage.content.trim()) {
      chat.title = makeFallbackTitle(content);
      render();
      if (chat.settings.generateTitles) generateChatTitle(chat);
    }
  }
}

function buildRequest(chat) {
  const settings = chat.settings;
  const contextCount = Number(settings.contextMessages || 16);
  const messages = chat.messages
    .filter((message) => message.content)
    .slice(-contextCount)
    .map(({ role, content }) => ({ role, content }));

  if (settings.systemPrompt?.trim()) {
    messages.unshift({ role: "system", content: settings.systemPrompt.trim() });
  }

  return {
    model: settings.model || "mistral",
    messages,
    options: {
      temperature: Number(settings.temperature ?? 0.7),
    },
  };
}

async function generateChatTitle(chat) {
  const firstUserMessage = chat.messages.find((message) => message.role === "user")?.content || "";
  const firstAssistantMessage = chat.messages.find((message) => message.role === "assistant")?.content || "";
  if (!firstUserMessage || !firstAssistantMessage || abortController) return;

  const controller = new AbortController();
  titleAbortController?.abort();
  titleAbortController = controller;
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: chat.settings.model || "mistral",
        messages: [
          {
            role: "system",
            content: "Create a concise chat title for the broad topic only. Use 2 to 4 words. Do not include a colon, subtitle, quotes, punctuation, labels, or extra text.",
          },
          {
            role: "user",
            content: `User asked:\n${firstUserMessage}\n\nAssistant answered:\n${firstAssistantMessage.slice(0, 1200)}`,
          },
        ],
        options: { temperature: 0.2 },
      }),
      signal: controller.signal,
    });
    if (!response.ok || !response.body) return;

    let title = "";
    await readStream(response.body, (chunk) => {
      title += chunk;
    });
    const cleaned = cleanTitle(title);
    if (cleaned && !controller.signal.aborted && !abortController) {
      chat.title = cleaned;
      chat.updatedAt = Date.now();
      render();
    }
  } catch (error) {
    if (error.name !== "AbortError") saveState();
  } finally {
    if (titleAbortController === controller) titleAbortController = null;
  }
}

function saveCurrentSettings() {
  const chat = ensureActiveChat();
  chat.settings = {
    model: els.modelSelect.value || "mistral",
    systemPrompt: els.systemPrompt.value,
    temperature: Number(els.temperatureInput.value || 0.7),
    contextMessages: Number(els.contextInput.value || 16),
    generateTitles: els.generateTitlesInput.checked,
  };
  saveState();
}

function deleteChat(id) {
  state.chats = state.chats.filter((chat) => chat.id !== id);
  if (state.activeChatId === id) state.activeChatId = state.chats[0]?.id || null;
  render();
}

function renameChat(id) {
  const chat = state.chats.find((item) => item.id === id);
  if (!chat) return;

  const title = prompt("Rename chat", chat.title);
  if (title === null) return;

  const cleaned = cleanManualTitle(title);
  if (!cleaned) return;

  chat.title = cleaned;
  chat.updatedAt = Date.now();
  render();
}

function stopGeneration() {
  abortController?.abort();
}

function setGenerating(isGenerating) {
  els.sendButton.disabled = isGenerating;
  els.promptInput.disabled = isGenerating;
  els.stopButton.hidden = !isGenerating;
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    els.messages.scrollTop = els.messages.scrollHeight;
  });
}

function closeMobileSidebar() {
  els.sidebar.classList.remove("open");
  els.menuButton.setAttribute("aria-expanded", "false");
}

function makeFallbackTitle(content) {
  const stopWords = new Set(["about", "after", "again", "also", "because", "before", "could", "from", "have", "into", "just", "like", "make", "more", "should", "that", "this", "with", "would", "what", "when", "where", "which", "your"]);
  const words = content
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, " ")
    .split(/\s+/)
    .filter((word) => word.length > 2 && !stopWords.has(word))
    .slice(0, 5);
  if (!words.length) return "New conversation";
  return words.map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}

function cleanTitle(title) {
  return title
    .replace(/["'`]/g, "")
    .replace(/^title:\s*/i, "")
    .split(":")[0]
    .replace(/[.?!:;]+$/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .slice(0, 4)
    .join(" ");
}

function cleanManualTitle(title) {
  return title.replace(/\s+/g, " ").trim().slice(0, 80);
}

function formatDate(timestamp) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(timestamp));
}

function showToast(message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  document.body.append(toast);
  setTimeout(() => toast.remove(), 4200);
}

function renderMarkdown(text) {
  const escaped = escapeHtml(text);
  const withBlocks = escaped.replace(/```([\s\S]*?)```/g, (_, code) => `<pre><code>${code.trim()}</code></pre>`);
  return withBlocks
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
