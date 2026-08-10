import { spawn } from "node:child_process";
import { mkdirSync, rmSync } from "node:fs";
import path from "node:path";

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9222;
const PROFILE = path.resolve("data", "edge-diag-profile");

mkdirSync(PROFILE, { recursive: true });

const edge = spawn(EDGE, [
  "--headless",
  "--disable-gpu",
  "--remote-debugging-port=" + PORT,
  "--user-data-dir=" + PROFILE,
  "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function getWebSocketUrl() {
  for (let i = 0; i < 40; i += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/json`);
      const targets = await response.json();
      const page = targets.find((target) => target.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch {
      // edge not ready yet
    }
    await sleep(250);
  }
  throw new Error("DevTools endpoint not available");
}

const wsUrl = await getWebSocketUrl();
const ws = new WebSocket(wsUrl);

let nextId = 1;
const pending = new Map();
const consoleMessages = [];

function send(method, params = {}) {
  return new Promise((resolve) => {
    const id = nextId++;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

ws.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    pending.get(message.id)(message);
    pending.delete(message.id);
    return;
  }
  if (message.method === "Runtime.exceptionThrown") {
    consoleMessages.push("EXCEPTION: " + JSON.stringify(message.params.exceptionDetails));
  }
  if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
    consoleMessages.push("CONSOLE: " + JSON.stringify(message.params.args));
  }
});

ws.addEventListener("open", async () => {
  await send("Runtime.enable");
  await send("Page.enable");
  await send("Page.navigate", { url: "http://127.0.0.1:8000/" });
  await sleep(1800);

  async function evaluate(expression) {
    const result = await send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    return result.result?.result?.value;
  }

  const initial = await evaluate(`({
    title: document.title,
    graphs: document.querySelectorAll(".graph-item").length,
    forceBtn: !!document.querySelector('[data-view="force"]'),
    galaxyHidden: document.getElementById("galaxyArea")?.hidden,
    galaxySvg: !!document.querySelector("#galaxyArea svg"),
  })`);

  await evaluate(`document.querySelector('[data-id="e250960b55a4"]')?.click()`);
  await sleep(1200);
  const opened = await evaluate(`({
    canvasTitle: document.getElementById("canvasTitle")?.textContent,
    nodes: document.querySelectorAll(".node-item").length,
  })`);

  await evaluate(`document.querySelector('[data-view="force"]')?.click()`);
  await sleep(1500);
  const force = await evaluate(`({
    hidden: document.getElementById("forceArea")?.hidden,
    galaxyHidden: document.getElementById("galaxyArea")?.hidden,
    svg: !!document.querySelector("#forceArea svg"),
    nodes: document.querySelectorAll("#forceArea .force-node").length,
    links: document.querySelectorAll("#forceArea .force-link").length,
  })`);

  await evaluate(`document.querySelector('[data-view="markdown"]')?.click()`);
  await sleep(1200);
  const outline = await evaluate(`({
    hidden: document.getElementById("outlineArea")?.hidden,
    rows: document.querySelectorAll(".outline-row").length,
  })`);

  await evaluate(`document.querySelector('[data-view="mermaid"]')?.click()`);
  await sleep(1200);
  const mermaid = await evaluate(`({
    hidden: document.getElementById("viewport")?.hidden,
    svg: !!document.querySelector("#diagramArea svg"),
    raw: document.querySelector("#diagramArea .raw-code")?.textContent?.slice(0, 80) || "",
  })`);

  const pages = await evaluate(`(async () => {
    const results = {};
    for (const name of ["home", "generate", "graphs", "galaxy", "review", "mine"]) {
      const btn = document.querySelector('[data-page="' + name + '"]');
      btn?.click();
      if (name === "galaxy") await new Promise((resolve) => setTimeout(resolve, 1200));
      results[name] = {
        active: document.getElementById("page-" + name)?.classList.contains("active") || false,
        navActive: btn?.classList.contains("active") || false,
        galaxySvg: name === "galaxy" ? !!document.querySelector("#galaxyArea svg") : null,
      };
    }
    return results;
  })()`);

  console.log(JSON.stringify({ initial, opened, force, outline, mermaid, pages, errors: consoleMessages }, null, 2));
  ws.close();
  edge.kill();
  try {
    rmSync(PROFILE, { recursive: true, force: true });
  } catch {
    // profile may still be locked by the browser process
  }
});
