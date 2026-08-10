import { on } from "../bus.js";

export function initStatusBar() {
  on("status", ({ text, tone }) => setStatus(text, tone));
}

export function setStatus(text, tone = "normal") {
  const statusText = document.getElementById("statusText");
  const dot = document.getElementById("statusDot");
  if (statusText) statusText.textContent = text;
  if (dot) {
    dot.className = "dot" + (tone === "busy" ? " busy" : tone === "error" ? " error" : "");
  }
}

export function toast(message, isError = false, duration = 2600) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    el.hidden = true;
  }, duration);
}
