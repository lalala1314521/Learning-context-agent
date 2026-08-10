import { api } from "./api.js";
import { initAskPanel } from "./components/askPanel.js";
import { emit, on } from "./bus.js";
import { initCanvasPanel, showGraph } from "./components/canvasPanel.js";
import { initHistoryPanel, refreshHistory } from "./components/historyPanel.js";
import { initInputPanel } from "./components/inputPanel.js";
import { initNodePanel, showNodes } from "./components/nodePanel.js";
import { initReviewPanel, refreshReview } from "./components/reviewPanel.js";
import { initSplitLayout } from "./components/splitLayout.js";
import { initStatusBar, setStatus, toast } from "./components/statusBar.js";

function boot() {
  initStatusBar();
  initInputPanel();
  initHistoryPanel();
  initCanvasPanel();
  initNodePanel();
  initReviewPanel();
  initAskPanel();
  initSplitLayout();

  const root = document.documentElement;
  const savedTheme = localStorage.getItem("lca-theme") || "light";
  root.dataset.theme = savedTheme;
  document.getElementById("themeToggle").checked = savedTheme === "dark";

  document.getElementById("themeToggle").addEventListener("change", (event) => {
    const theme = event.target.checked ? "dark" : "light";
    root.dataset.theme = theme;
    localStorage.setItem("lca-theme", theme);
    emit("theme-changed");
    setStatus(`已切换到${theme === "dark" ? "暗色" : "亮色"}模式`);
  });

  on("generate", async (payload) => {
    const generateBtn = document.getElementById("generateBtn");
    setStatus("正在生成脉络...", "busy");
    generateBtn.disabled = true;
    try {
      const data = await api("/graphs/generate", { method: "POST", body: payload });
      if (data.id) {
        data.links = await api(`/links?graph_id=${encodeURIComponent(data.id)}`);
      }
      showGraph(data);
      showNodes(data);
      refreshHistory();
      refreshReview();
      refreshStats();
      setStatus(`已生成 ${data.id}`);
      if (data.auto_links && data.auto_links.length) {
        toast(`已自动关联 ${data.auto_links.length} 个跨脉络知识点`);
      }
    } catch (error) {
      toast(error.message, true);
      setStatus("生成失败", "error");
    } finally {
      generateBtn.disabled = false;
    }
  });

  on("open-graph", async (payload) => {
    const graphId = typeof payload === "object" ? payload.graphId : payload;
    if (!graphId) return;
    if (typeof payload === "object" && payload.nodeId) {
      window.__highlightNode = payload.nodeId;
    }
    setStatus("正在打开脉络...", "busy");
    try {
      const [data, links] = await Promise.all([
        api(`/graphs/${encodeURIComponent(graphId)}`),
        api(`/links?graph_id=${encodeURIComponent(graphId)}`),
      ]);
      data.links = links;
      showGraph(data);
      showNodes(data);
      refreshReview();
      refreshStats();
      setStatus(`已打开 ${graphId}`);
    } catch (error) {
      toast(error.message, true);
      setStatus("打开失败", "error");
    }
  });

  refreshHistory();
  refreshStats();
}

async function refreshStats() {
  try {
    const [graphs, review] = await Promise.all([
      api("/graphs"),
      api("/review"),
    ]);
    document.getElementById("statGraphs").textContent = graphs.length;
    document.getElementById("statReview").textContent = review.stats.due || 0;
    const total = review.stats.total || 0;
    document.getElementById("statNodes").textContent = total;
    const mastered = review.stats.mastered || 0;
    const pct = total ? Math.round((mastered / total) * 100) : 0;
    document.getElementById("goalBar").style.width = `${pct}%`;
    document.getElementById("goalPct").textContent = `${pct}%`;
    updateMastery(pct, total);
  } catch {
    // 统计加载失败不阻塞界面
  }
}

function updateMastery(pct, total) {
  const ring = document.getElementById("masteryRing");
  const arc = document.getElementById("masteryArc");
  const bar = document.getElementById("masteryBar");
  const hint = document.getElementById("masteryHint");
  if (ring) {
    const circumference = 2 * Math.PI * 18;
    const offset = circumference * (1 - pct / 100);
    arc.setAttribute("d", `M22 4a18 18 0 0 1 15.2 8.5`);
    arc.setAttribute("stroke-dasharray", `${circumference}`);
    arc.setAttribute("stroke-dashoffset", String(offset));
    arc.setAttribute("stroke", pct >= 80 ? "#10B981" : pct >= 40 ? "#FFC857" : "#FF7A45");
  }
  if (bar) bar.style.width = `${pct}%`;
  if (hint) hint.textContent = `已完成 ${total} 次复习 · 掌握 ${pct}%`;
}

window.addEventListener("DOMContentLoaded", boot);
window.refreshStats = refreshStats;
