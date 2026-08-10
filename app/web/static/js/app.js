import { api } from "./api.js";
import { initAskPanel } from "./components/askPanel.js";
import { emit, on } from "./bus.js";
import { initCanvasPanel, showGraph } from "./components/canvasPanel.js";
import {
  hideGalaxy,
  initGalaxyPanel,
  refreshGalaxy,
  showGalaxy,
} from "./components/galaxyPanel.js";
import { initHistoryPanel, refreshHistory } from "./components/historyPanel.js";
import { initInputPanel } from "./components/inputPanel.js";
import { openModal } from "./components/modal.js";
import { initNodePanel, showNodes } from "./components/nodePanel.js";
import { initReviewPanel, refreshReview } from "./components/reviewPanel.js";
import { initStatusBar, setStatus, toast } from "./components/statusBar.js";

let currentPage = "home";
let galaxyDirty = false;

function boot() {
  initStatusBar();
  initPageNavigation();
  initInputPanel();
  initHistoryPanel();
  initCanvasPanel();
  initGalaxyPanel();
  initNodePanel();
  initReviewPanel();
  initAskPanel();
  initSourceActions();

  document.addEventListener("review-updated", () => {
    galaxyDirty = true;
    refreshStats();
    if (currentPage === "galaxy") refreshGalaxy();
  });

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
    const loading = document.getElementById("canvasLoading");
    loading.hidden = false;
    const tracePanel = document.getElementById("agentTrace");
    if (tracePanel) tracePanel.hidden = true;
    try {
      const job = await api("/graphs/generate/async", { method: "POST", body: payload });
      const data = await pollJob(job.id);
      loading.hidden = true;
      if (data.id) {
        data.links = await api(`/links?graph_id=${encodeURIComponent(data.id)}`);
      }
      showGraph(data);
      showNodes(data);
      galaxyDirty = true;
      showReport(data.concept_report);
      refreshHistory();
      refreshReview();
      refreshStats();
      showPage("graphs");
      setStatus(`已生成 ${data.id}`);
      if (data.auto_links && data.auto_links.length) {
        toast(`已自动关联 ${data.auto_links.length} 个跨脉络知识点`);
      }
      if (data.long_text_report && data.long_text_report.chunks) {
        toast(`长文处理完成：${data.long_text_report.chunks} 个分块`);
      }
    } catch (error) {
      loading.hidden = true;
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
      hideReport();
      showGraph(data);
      showNodes(data);
      refreshReview();
      refreshStats();
      showPage("graphs");
      setStatus(`已打开 ${graphId}`);
    } catch (error) {
      toast(error.message, true);
      setStatus("打开失败", "error");
    }
  });

  refreshHistory();
  refreshStats();
  showPage("home");
}

function initPageNavigation() {
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.addEventListener("click", () => showPage(button.dataset.page));
  });
  document.querySelectorAll("[data-go]").forEach((button) => {
    button.addEventListener("click", () => showPage(button.dataset.go));
  });
}

async function showPage(name) {
  currentPage = name;
  document.querySelectorAll(".page").forEach((page) => {
    page.classList.toggle("active", page.id === `page-${name}`);
  });
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === name);
  });
  if (name === "galaxy") {
    if (galaxyDirty) {
      galaxyDirty = false;
      await showGalaxy(true);
    } else {
      await showGalaxy();
    }
  } else {
    hideGalaxy();
  }
}

function initSourceActions() {
  document.getElementById("vaultImportBtn")?.addEventListener("click", () => {
    openModal({
      title: "导入 Obsidian",
      fields: [
        { key: "path", label: "Vault 目录路径", placeholder: "C:\\notes\\my-vault" },
        { key: "limit", label: "最多导入数量（可选）" },
      ],
      confirmText: "开始导入",
      onConfirm: async (values) => {
        const result = await api("/sources/import-vault", {
          method: "POST",
          body: { path: values.path, limit: values.limit ? Number(values.limit) : null },
        });
        showSourceResult(`已导入 ${result.imported} 个 Markdown 文件`);
      },
    });
  });

  document.getElementById("videoSubtitleBtn")?.addEventListener("click", () => {
    openModal({
      title: "视频字幕",
      fields: [
        { key: "url", label: "字幕文件 URL 或 YouTube 链接" },
      ],
      confirmText: "获取字幕",
      onConfirm: async (values) => {
        const result = await api("/sources/video-subtitle", {
          method: "POST",
          body: { url: values.url },
        });
        document.getElementById("contentInput").value = result.content;
        showSourceResult(`已获取字幕：${result.source_name}，${result.preview?.blocks || 1} 块`);
        showPage("generate");
      },
    });
  });
}

function showSourceResult(message) {
  const el = document.getElementById("sourceResult");
  if (!el) return;
  el.textContent = message;
  el.hidden = false;
}

async function pollJob(jobId) {
  const loading = document.getElementById("canvasLoading");
  for (;;) {
    const job = await api(`/jobs/${encodeURIComponent(jobId)}`);
    renderTrace(job);
    if (job.status === "done") return job.result;
    if (job.status === "error") throw new Error(job.error || "生成失败");
    if (job.progress > 5) {
      loading.querySelector(".loading-text").textContent =
        `生成中 ${job.progress}% · ${job.stage}`;
    }
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
}

function renderTrace(job) {
  const panel = document.getElementById("agentTrace");
  if (!panel) return;
  if (job.status === "done" && !(job.trace && job.trace.length)) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const tokens = job.total_tokens || 0;
  const elapsed = ((job.elapsed_ms || 0) / 1000).toFixed(1);
  const remaining = estimateRemaining(job);
  const meta = `${elapsed}s · ~${tokens} tokens${remaining ? ` · 预计还剩约 ${remaining}s` : ""}`;
  const body = (job.trace && job.trace.length)
    ? job.trace.map(renderTraceEvent).join("")
    : '<div class="trace-event trace-thought"><span class="trace-icon">💭</span>' +
      '<div class="trace-content"><div class="trace-text">正在初始化 Agent…</div></div></div>';
  panel.innerHTML = `
    <div class="agent-trace-head">
      <span class="agent-trace-title">🤖 Agent 过程</span>
      <span class="agent-trace-meta">${escapeHtml(meta)}</span>
    </div>
    <div class="agent-trace-body">${body}</div>`;
  panel.scrollTop = panel.scrollHeight;
}

function renderTraceEvent(ev) {
  const icon = ev.type === "thought" ? "💭"
    : ev.type === "action" ? "🛠️"
    : ev.type === "tool" ? "⚙️"
    : ev.type === "done" ? "✅" : "·";
  const detail = ev.detail ? `<div class="trace-detail">${escapeHtml(ev.detail)}</div>` : "";
  const ms = ev.ms ? `<span class="trace-ms">+${ev.ms}ms</span>` : "";
  return `<div class="trace-event trace-${ev.type}">
    <span class="trace-icon">${icon}</span>
    <div class="trace-content">
      <div class="trace-text">${escapeHtml(ev.text)}${ms}</div>
      ${detail}
    </div>
  </div>`;
}

function estimateRemaining(job) {
  if (job.status === "done" || job.status === "error") return "";
  const pct = Math.max(5, job.progress || 5);
  const elapsed = (job.elapsed_ms || 0) / 1000;
  if (elapsed <= 0 || pct >= 95) return "";
  const total = elapsed / (pct / 100);
  return Math.max(0, Math.round(total - elapsed));
}

function showReport(report) {
  const el = document.getElementById("ahaReport");
  if (!el) return;
  if (!report || !report.aligned_mentions) {
    el.hidden = true;
    return;
  }
  const newLinks = report.new_links || [];
  const reinforced = report.reinforced || [];
  const newConcepts = report.new_concepts || [];
  const rows = [
    ...newLinks.map((link) =>
      `<div class="aha-row"><span class="aha-new">新连接</span><b>${escapeHtml(link.from_label)}</b> → <b>${escapeHtml(link.to_label)}</b><span class="aha-meta">${escapeHtml(link.relation_type)} · ${Math.round((link.confidence || 0) * 100)}%</span></div>`),
    ...reinforced.slice(0, 5).map((item) =>
      `<div class="aha-row"><span class="aha-reinforce">强化</span><b>${escapeHtml(item.label)}</b><span class="aha-meta">第 ${item.mention_count || 1} 次提及</span></div>`),
    ...newConcepts.slice(0, 5).map((item) =>
      `<div class="aha-row"><span class="aha-new">新概念</span><b>${escapeHtml(item.label)}</b></div>`),
  ];
  el.hidden = false;
  el.innerHTML = `
    <div class="aha-heading">本次融会贯通</div>
    <div class="aha-summary">${report.aligned_mentions} 个提及已对齐，${newLinks.length} 条新连接</div>
    ${rows.join("") || '<div class="aha-row">本次没有发现新连接</div>'}`;
}

function hideReport() {
  const el = document.getElementById("ahaReport");
  if (el) el.hidden = true;
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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
    const homeBar = document.getElementById("homeGoalBar");
    const homePct = document.getElementById("homeGoalPct");
    if (homeBar) homeBar.style.width = `${pct}%`;
    if (homePct) homePct.textContent = `${pct}%`;
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
