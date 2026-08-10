import { esc } from "../util.js";

/** 在指定容器内实时渲染 Agent 轨迹（思考/工具/后处理 + tokens + 耗时）。
 *  生成与知识问答共用。
 */
export function renderAgentTrace(job, containerId) {
  const panel = document.getElementById(containerId);
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
      <span class="agent-trace-meta">${esc(meta)}</span>
    </div>
    <div class="agent-trace-body">${body}</div>`;
  panel.scrollTop = panel.scrollHeight;
}

function renderTraceEvent(ev) {
  const icon = ev.type === "thought" ? "💭"
    : ev.type === "action" ? "🛠️"
    : ev.type === "tool" ? "⚙️"
    : ev.type === "done" ? "✅" : "·";
  const detail = ev.detail ? `<div class="trace-detail">${esc(ev.detail)}</div>` : "";
  const ms = ev.ms ? `<span class="trace-ms">+${ev.ms}ms</span>` : "";
  return `<div class="trace-event trace-${ev.type}">
    <span class="trace-icon">${icon}</span>
    <div class="trace-content">
      <div class="trace-text">${esc(ev.text)}${ms}</div>
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
