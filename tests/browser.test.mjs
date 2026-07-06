import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import test from "node:test";

import { chromium } from "playwright-core";


const ROOT = new URL("../", import.meta.url).pathname;
const WEB_ROOT = join(ROOT, "web");
const CHROME_PATHS = [
  process.env.CHROME_BIN,
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
  "/usr/bin/chromium",
].filter(Boolean);
const CHROME = CHROME_PATHS.find(existsSync);
let browser;
let server;
let baseUrl;


function sendJson(response, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(200, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body),
  });
  response.end(body);
}


test.before(async () => {
  assert(CHROME, "Chrome or Chromium is required for browser accessibility tests");
  server = createServer((request, response) => {
    if (request.url === "/api/models") {
      sendJson(response, {
        models: [{ name: "mistral" }],
        runningModels: ["mistral"],
        activeModel: "mistral",
        defaultModel: "mistral",
      });
      return;
    }
    const pathname = request.url.split("?", 1)[0];
    const relative = pathname === "/" ? "index.html" : pathname.slice(1);
    const file = normalize(join(WEB_ROOT, relative));
    if (!file.startsWith(WEB_ROOT)) {
      response.writeHead(403).end();
      return;
    }
    import("node:fs").then(({ createReadStream }) => {
      const contentTypes = {
        ".css": "text/css",
        ".html": "text/html",
        ".js": "text/javascript",
      };
      const stream = createReadStream(file);
      stream.on("error", () => response.writeHead(404).end());
      stream.on("open", () => {
        response.writeHead(200, {
          "Content-Type": contentTypes[extname(file)] ?? "application/octet-stream",
        });
        stream.pipe(response);
      });
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  baseUrl = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({
    executablePath: CHROME,
    headless: true,
    args: ["--no-sandbox"],
  });
});


test.after(async () => {
  await browser?.close();
  await new Promise((resolve) => server?.close(resolve));
});


async function seededPage(context) {
  const page = await context.newPage();
  await page.goto(baseUrl);
  await page.evaluate(() => {
    const now = Date.now();
    localStorage.setItem(
      "local-mistral-chat-state-v1",
      JSON.stringify({
        schemaVersion: 2,
        activeChatId: "first",
        chats: [
          {
            id: "first",
            title: "First chat",
            createdAt: now,
            updatedAt: now,
            messages: [{ role: "user", content: "First", createdAt: now }],
            settings: {},
          },
          {
            id: "second",
            title: "Second chat",
            createdAt: now - 1,
            updatedAt: now - 1,
            messages: [{ role: "user", content: "Second", createdAt: now - 1 }],
            settings: {},
          },
        ],
      }),
    );
  });
  await page.reload();
  await page.getByRole("button", { name: "Settings" }).waitFor();
  return page;
}


async function focusIndicator(locator) {
  await locator.focus();
  await locator.press("Tab");
  await locator.page().keyboard.press("Shift+Tab");
  return locator.evaluate((element) => {
    const own = getComputedStyle(element);
    const composer = element.closest(".composer");
    const parent = composer ? getComputedStyle(composer) : null;
    return {
      ownWidth: parseFloat(own.outlineWidth),
      ownStyle: own.outlineStyle,
      parentWidth: parent ? parseFloat(parent.outlineWidth) : 0,
      parentStyle: parent?.outlineStyle ?? "none",
    };
  });
}


for (const colorScheme of ["light", "dark"]) {
  test(`keyboard focus is visible for every control in ${colorScheme} theme`, async () => {
    const context = await browser.newContext({ colorScheme });
    const page = await seededPage(context);
    await page.getByRole("button", { name: "Settings" }).click();
    const controls = page.locator("button:visible, input:visible, textarea:visible, select:visible");
    const count = await controls.count();
    assert(count > 10);
    for (let index = 0; index < count; index += 1) {
      const indicator = await focusIndicator(controls.nth(index));
      const ownVisible = indicator.ownWidth >= 2 && indicator.ownStyle !== "none";
      const parentVisible =
        indicator.parentWidth >= 2 && indicator.parentStyle !== "none";
      assert(
        ownVisible || parentVisible,
        `control ${index} lacks a visible focus indicator in ${colorScheme}`,
      );
    }
    await context.close();
  });
}


test("chat history buttons have independent keyboard behavior and restored focus", async () => {
  const context = await browser.newContext();
  const page = await seededPage(context);
  const openSecond = page.getByRole("button", { name: "Open chat: Second chat" });
  await openSecond.focus();
  await page.keyboard.press("Tab");
  assert.equal(
    await page.evaluate(() => document.activeElement?.getAttribute("aria-label")),
    "Rename chat: Second chat",
  );
  await page.keyboard.press("Tab");
  assert.equal(
    await page.evaluate(() => document.activeElement?.getAttribute("aria-label")),
    "Delete chat: Second chat",
  );
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Enter");
  await assert.doesNotReject(
    page.getByRole("button", { name: "Open chat: Second chat" }).waitFor(),
  );
  assert.equal(await page.locator(".open-chat[aria-current=page]").getAttribute("data-chat-id"), "second");
  assert.equal(await page.locator(".open-chat").count(), 2);
  await page.waitForFunction(
    () => document.activeElement?.getAttribute("aria-label") === "Open chat: Second chat",
  );
  assert.equal(
    await page.evaluate(() => document.activeElement?.getAttribute("aria-label")),
    "Open chat: Second chat",
  );

  page.once("dialog", (dialog) => dialog.accept("Renamed chat"));
  const rename = page.getByRole("button", { name: "Rename chat: Second chat" });
  await rename.focus();
  await page.keyboard.press("Space");
  await page.getByRole("button", { name: "Rename chat: Renamed chat" }).waitFor();
  assert.equal(await page.locator(".open-chat").count(), 2);
  await page.waitForFunction(
    () => document.activeElement?.getAttribute("aria-label") === "Rename chat: Renamed chat",
  );
  assert.equal(
    await page.evaluate(() => document.activeElement?.getAttribute("aria-label")),
    "Rename chat: Renamed chat",
  );

  const remove = page.getByRole("button", { name: "Delete chat: Renamed chat" });
  await remove.focus();
  await page.keyboard.press("Enter");
  assert.equal(await page.locator(".open-chat").count(), 1);
  await page.waitForFunction(
    () => document.activeElement?.classList.contains("open-chat"),
  );
  assert.equal(
    await page.evaluate(() => document.activeElement?.classList.contains("open-chat")),
    true,
  );
  await context.close();
});


test("accessibility tree exposes toggle names, relationships, and changing state", async () => {
  const context = await browser.newContext({ viewport: { width: 600, height: 800 } });
  const page = await seededPage(context);
  const session = await context.newCDPSession(page);
  const tree = await session.send("Accessibility.getFullAXTree");
  const button = (name) =>
    tree.nodes.find((node) => node.role?.value === "button" && node.name?.value === name);
  const property = (node, name) =>
    node.properties?.find((candidate) => candidate.name === name);

  const menu = button("Toggle sidebar");
  const settings = button("Settings");
  assert(menu);
  assert(settings);
  assert.equal(property(menu, "expanded")?.value?.value, false);
  assert(property(menu, "controls"));
  assert.equal(property(settings, "expanded")?.value?.value, false);
  assert.equal(
    await page.getByRole("button", { name: "Settings" }).getAttribute("aria-controls"),
    "settingsPanel",
  );

  await page.getByRole("button", { name: "Toggle sidebar" }).press("Enter");
  assert.equal(
    await page.getByRole("button", { name: "Toggle sidebar" }).getAttribute("aria-expanded"),
    "true",
  );
  await page.getByRole("button", { name: "Toggle sidebar" }).press("Space");
  assert.equal(
    await page.getByRole("button", { name: "Toggle sidebar" }).getAttribute("aria-expanded"),
    "false",
  );
  await page.getByRole("button", { name: "Settings" }).press("Enter");
  assert.equal(
    await page.getByRole("button", { name: "Settings" }).getAttribute("aria-expanded"),
    "true",
  );
  const expandedTree = await session.send("Accessibility.getFullAXTree");
  const expandedSettings = expandedTree.nodes.find(
    (node) => node.role?.value === "button" && node.name?.value === "Settings",
  );
  assert.equal(property(expandedSettings, "expanded")?.value?.value, true);
  assert(property(expandedSettings, "controls"));
  await page.getByRole("button", { name: "Settings" }).press("Space");
  assert.equal(
    await page.getByRole("button", { name: "Settings" }).getAttribute("aria-expanded"),
    "false",
  );
  await context.close();
});
