import { api } from "../api.js";
import { emit } from "../bus.js";
import { esc } from "../util.js";

export function initHistoryPanel() {
  const searchInput = document.getElementById("searchInput");
  document.getElementById("searchBtn").addEventListener("click", () => {
    refreshHistory(searchInput.value.trim());
  });
  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") refreshHistory(searchInput.value.trim());
  });
  document.getElementById("refreshBtn").addEventListener("click", () => {
    refreshHistory(searchInput.value.trim());
  });
  refreshHistory();
}

export async function refreshHistory(query = "") {
  try {
    const [graphs, memories] = await Promise.all([
      api("/graphs" + (query ? `?q=${encodeURIComponent(query)}` : "")),
      api("/memories"),
    ]);
    renderGraphs(graphs);
    renderMemories(memories);
  } catch {
    document.getElementById("graphList").innerHTML = '<div class="empty-state small">加载失败</div>';
  }
}

function renderGraphs(graphs) {
  const el = document.getElementById("graphList");
  if (!graphs.length) {
    el.innerHTML = '<div class="empty-state small">暂无脉络，先生成一张</div>';
    return;
  }
  el.innerHTML = graphs
    .map((graph) => {
      const time = String(graph.updated_at || "").slice(0, 16).replace("T", " ");
      return `
        <div class="graph-item" data-id="${esc(graph.id)}">
          <div class="graph-title">${esc(graph.title || "未命名")}</div>
          <div class="graph-meta">${esc(graph.graph_type || "auto")} · ${esc(graph.source_type || "text")} · ${esc(time)}</div>
        </div>`;
    })
    .join("");
  el.querySelectorAll(".graph-item").forEach((item) => {
    item.addEventListener("click", () => emit("open-graph", item.dataset.id));
  });
}

function renderMemories(memories) {
  const el = document.getElementById("memoryList");
  document.getElementById("memoryCount").textContent = `${memories.length} 条`;
  if (!memories.length) {
    el.innerHTML = '<div class="empty-state small">暂无记忆快照</div>';
    return;
  }
  el.innerHTML = memories
    .map((memory) => {
      const points = (memory.key_points || [])
        .map((point) => `<span>${esc(point)}</span>`)
        .join("");
      const time = String(memory.created_at || "").slice(0, 16).replace("T", " ");
      return `
        <div class="memory-item">
          <div class="memory-summary">${esc(memory.summary)}</div>
          <div class="memory-meta">${esc(time)}</div>
          ${points ? `<div class="memory-points">${points}</div>` : ""}
        </div>`;
    })
    .join("");
}
