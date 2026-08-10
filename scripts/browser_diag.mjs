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

  const drag = await evaluate(`(() => {
    const root = document.documentElement;
    const splitter = document.querySelector(".splitter-left");
    const rect = splitter.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const before = parseFloat(getComputedStyle(document.querySelector(".input-panel")).width);
    splitter.dispatchEvent(new PointerEvent("pointerdown", { clientX: x, clientY: y, bubbles: true, pointerId: 1 }));
    document.dispatchEvent(new PointerEvent("pointermove", { clientX: x + 90, clientY: y, bubbles: true, pointerId: 1 }));
    document.dispatchEvent(new PointerEvent("pointerup", { clientX: x + 90, clientY: y, bubbles: true, pointerId: 1 }));
    const after = parseFloat(getComputedStyle(document.querySelector(".input-panel")).width);
    const grid = document.querySelector(".grid-main");
    return {
      before,
      after,
      gridVar: grid.style.getPropertyValue("--left-w"),
      columns: getComputedStyle(grid).gridTemplateColumns,
    };
  })()`);

  const collapsed = await evaluate(`(() => {
    const btn = document.querySelector('[data-collapse="input"]');
    btn?.click();
    const panel = document.querySelector(".input-panel");
    const afterClick = {
      collapsed: panel?.classList.contains("collapsed"),
      width: panel ? parseFloat(getComputedStyle(panel).width) : 0,
      buttonVisible: btn ? getComputedStyle(btn).display !== "none" && btn.offsetWidth > 0 : false,
      gridVar: document.querySelector(".grid-main").style.getPropertyValue("--left-w"),
      columns: getComputedStyle(document.querySelector(".grid-main")).gridTemplateColumns,
    };
    btn?.click();
    return {
      afterClick,
      expanded: !panel?.classList.contains("collapsed"),
    };
  })()`);

  console.log(JSON.stringify({ initial, opened, force, outline, mermaid, drag, collapsed, errors: consoleMessages }, null, 2));
  ws.close();
  edge.kill();
  try {
    rmSync(PROFILE, { recursive: true, force: true });
  } catch {
    // profile may still be locked by the browser process
  }
});
