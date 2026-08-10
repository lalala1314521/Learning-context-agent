import { api } from "../api.js";
import { emit } from "../bus.js";
import { esc } from "../util.js";
import { openModal } from "./modal.js";
import { setStatus, toast } from "./statusBar.js";

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
          <button type="button" class="graph-delete" data-delete="${esc(graph.id)}" title="删除脉络">删</button>
        </div>`;
    })
    .join("");
  el.querySelectorAll(".graph-item").forEach((item) => {
    item.addEventListener("click", () => emit("open-graph", item.dataset.id));
  });
  el.querySelectorAll("[data-delete]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const graphId = button.dataset.delete;
      openModal({
        title: "删除脉络",
        fields: [{
          key: "message",
          label: "",
          value: `确认删除脉络 ${graphId}？节点、题目和复习记录会一起删除。`,
          type: "textarea",
        }],
        confirmText: "删除",
        onConfirm: async () => {
          await api(`/graphs/${encodeURIComponent(graphId)}`, { method: "DELETE" });
          setStatus("脉络已删除");
          await refreshHistory();
          if (window.refreshStats) window.refreshStats();
        },
      });
    });
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
