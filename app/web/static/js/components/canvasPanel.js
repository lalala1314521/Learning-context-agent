import { api } from "../api.js";
import { on } from "../bus.js";
import { downloadFile, esc } from "../util.js";
import { destroyForceGraph, renderForceGraph } from "./forceGraph.js";
import { hideGalaxy, showGalaxy } from "./galaxyPanel.js";

let current = null;
let currentNodes = [];
let currentLinks = [];
let currentConceptLinks = [];
let view = "galaxy";
let zoom = 1;

export function initCanvasPanel() {
  document.querySelectorAll(".seg").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".seg").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      view = button.dataset.view;
      renderCurrent();
    });
  });

  const viewport = document.getElementById("viewport");
  document.getElementById("zoomInBtn").addEventListener("click", () => setZoom(zoom * 1.15));
  document.getElementById("zoomOutBtn").addEventListener("click", () => setZoom(zoom / 1.15));
  document.getElementById("fitBtn").addEventListener("click", fitToViewport);
  document.getElementById("fullscreenBtn").addEventListener("click", toggleFullscreen);
  viewport.addEventListener("wheel", (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    setZoom(zoom * (event.deltaY > 0 ? 0.9 : 1.1));
  }, { passive: false });

  let dragging = null;
  viewport.addEventListener("mousedown", (event) => {
    dragging = { x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop };
    viewport.classList.add("dragging");
  });
  document.addEventListener("mousemove", (event) => {
    if (!dragging) return;
    viewport.scrollLeft = dragging.left - (event.clientX - dragging.x);
    viewport.scrollTop = dragging.top - (event.clientY - dragging.y);
  });
  document.addEventListener("mouseup", () => {
    dragging = null;
    viewport.classList.remove("dragging");
  });

  document.getElementById("exportBtn").addEventListener("click", exportCurrent);
  on("theme-changed", renderCurrent);
}

export function showGraph(data) {
  const graph = data.graph || data;
  current = graph;
  currentNodes = data.nodes || [];
  currentLinks = data.links || [];
  currentConceptLinks = data.concept_links || [];
  document.getElementById("canvasTitle").textContent = graph.title || "脉络画布";
  document.getElementById("emptyState").hidden = true;
  document.getElementById("canvasLoading").hidden = true;
  document.getElementById("galaxyArea").hidden = view !== "galaxy";
  document.getElementById("viewport").hidden = view !== "mermaid";
  document.getElementById("forceArea").hidden = view !== "force";
  document.getElementById("outlineArea").hidden = view !== "markdown";
  document.getElementById("statusGraph").textContent = graph.id ? `图: ${graph.id}` : "";
  renderCurrent();
}

async function renderCurrent() {
  const viewport = document.getElementById("viewport");
  const force = document.getElementById("forceArea");
  const outline = document.getElementById("outlineArea");

  if (view === "galaxy") {
    viewport.hidden = true;
    outline.hidden = true;
    force.hidden = true;
    await showGalaxy();
    return;
  }

  hideGalaxy();
  if (!current) return;

  if (view === "force") {
    viewport.hidden = true;
    outline.hidden = true;
    force.hidden = false;
    renderForceGraph(current, currentNodes, currentLinks, currentConceptLinks);
    return;
  }

  if (view === "markdown") {
    destroyForceGraph();
    viewport.hidden = true;
    outline.hidden = false;
    await loadOutline();
    return;
  }

  viewport.hidden = false;
  destroyForceGraph();
  outline.hidden = true;
  const code = current.mermaid_code || current.mermaid || "";
  if (!code) {
    document.getElementById("diagramArea").innerHTML =
      '<div class="empty-state small">当前脉络没有 Mermaid 代码</div>';
    return;
  }
  await renderMermaid(code, document.getElementById("diagramArea"));
}

async function loadOutline() {
  if (!current || !current.id) return;
  const area = document.getElementById("outlineArea");
  try {
    const outline = await api(`/graphs/${encodeURIComponent(current.id)}/outline`);
    area.innerHTML = outline.map((node) => renderOutlineNode(node)).join("") ||
      '<div class="empty-state small">暂无大纲</div>';
    area.querySelectorAll(".outline-row").forEach((row) => {
      row.addEventListener("click", () => {
        const nodeId = row.dataset.id;
        const children = row.nextElementSibling;
        const toggle = row.querySelector(".outline-toggle");
        if (children.hidden) {
          children.hidden = false;
          toggle.textContent = "▼";
        } else {
          children.hidden = true;
          toggle.textContent = "▶";
        }
      });
    });
  } catch {
    area.innerHTML = '<div class="empty-state small">大纲加载失败</div>';
  }
}

function renderOutlineNode(node) {
  const children = node.children || [];
  const hasChildren = children.length > 0;
  return `
    <div class="outline-node">
      <div class="outline-row" data-id="${esc(node.id)}">
        <button type="button" class="outline-toggle" tabindex="-1">${hasChildren ? "▶" : "·"}</button>
        <span class="outline-label">${esc(node.label)}</span>
        ${node.note ? '<span class="panel-tag">含详情</span>' : ""}
      </div>
      <div class="outline-children" ${hasChildren ? "hidden" : ""}>
        ${node.note ? `<div class="outline-note">${esc(node.note)}</div>` : ""}
        ${children.map((child) => renderOutlineNode(child)).join("")}
      </div>
    </div>`;
}

async function renderMermaid(code, area) {
  area.innerHTML = '<div class="diagram-loading">渲染中...</div>';
  if (!window.mermaid) {
    area.innerHTML = `<pre class="raw-code">${esc(code)}</pre>`;
    return;
  }
  const theme = document.documentElement.dataset.theme === "dark" ? "dark" : "default";
  window.mermaid.initialize({
    startOnLoad: false,
    theme,
    securityLevel: "loose",
    fontFamily: '-apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
    themeVariables: {
      fontSize: "16px",
      nodeTextColor: theme === "dark" ? "#e5e7eb" : "#1f2937",
    },
  });
  try {
    const id = `mmd-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
    const { svg } = await window.mermaid.render(id, normalizeMermaid(code));
    area.innerHTML = svg;
    fitToViewport();
  } catch {
    const fallback = buildFallbackMermaid();
    if (fallback) {
      try {
        const fallbackId = `mmd-fallback-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
        const { svg } = await window.mermaid.render(fallbackId, fallback);
        area.innerHTML = svg;
        area.insertAdjacentHTML(
          "beforeend",
          '<div class="diagram-error">原始 Mermaid 语法不兼容，已使用节点结构降级图</div>',
        );
        fitToViewport();
        return;
      } catch {
        // fall through to raw code
      }
    }
    area.innerHTML = `
      <pre class="raw-code">${esc(code)}</pre>
      <div class="diagram-error">Mermaid 渲染失败，已显示原始代码</div>`;
  }
}

function normalizeMermaid(code) {
  return String(code || "")
    .replace(/```mermaid\s*\n?/gi, "")
    .replace(/```/g, "")
    .replace(/【Mermaid】:\s*/g, "")
    .replace(/\r\n/g, "\n")
    .trim();
}

function buildFallbackMermaid() {
  const nodes = currentNodes || [];
  if (!nodes.length) return "";
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const lines = ["graph TD"];
  const nodeIds = new Map();
  nodes.forEach((node, index) => {
    const id = `N${index}`;
    nodeIds.set(node.id, id);
    const label = String(node.label || "未命名")
      .replace(/["[\]]/g, "")
      .replace(/\n/g, " ")
      .slice(0, 40);
    lines.push(`    ${id}["${label}"]`);
  });
  nodes.forEach((node) => {
    if (node.parent_id && nodeIds.has(node.parent_id) && nodeIds.has(node.id)) {
      lines.push(`    ${nodeIds.get(node.parent_id)} --> ${nodeIds.get(node.id)}`);
    }
    (node.related_nodes || []).forEach((targetId) => {
      if (nodeIds.has(targetId) && nodeIds.has(node.id) && targetId !== node.id) {
        lines.push(`    ${nodeIds.get(node.id)} --- ${nodeIds.get(targetId)}`);
      }
    });
  });
  return lines.join("\n");
}

function setZoom(next) {
  zoom = Math.min(3, Math.max(0.2, next));
  document.getElementById("diagramArea").style.transform = `scale(${zoom})`;
  document.getElementById("zoomLevel").textContent = `${Math.round(zoom * 100)}%`;
}

function fitToViewport() {
  const svg = document.querySelector("#diagramArea svg");
  const viewport = document.getElementById("viewport");
  if (!svg || !viewport.clientWidth) return;
  const rect = svg.getBoundingClientRect();
  const scale = Math.min(
    viewport.clientWidth / (rect.width || 1),
    viewport.clientHeight / (rect.height || 1),
    1,
  );
  setZoom(Math.max(0.2, scale));
}

function toggleFullscreen() {
  const panel = document.querySelector(".canvas-panel");
  if (!document.fullscreenElement) {
    panel.requestFullscreen().catch(() => {});
  } else {
    document.exitFullscreen().catch(() => {});
  }
}

function exportCurrent() {
  if (!current) return;
  const base = current.id || "graph";
  const mermaid = current.mermaid_code || current.mermaid || "";
  const markdown = current.markdown_outline || current.markdown || "";
  if (view === "markdown" && markdown) {
    downloadFile(markdown, `${base}.md`, "text/markdown");
  } else if (mermaid) {
    downloadFile(mermaid, `${base}.mmd`, "text/plain");
  } else {
    downloadFile(JSON.stringify(current, null, 2), `${base}.json`, "application/json");
  }
}
