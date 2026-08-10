import { api } from "../api.js";
import { esc, renderMarkdown } from "../util.js";
import { renderAgentTrace } from "./trace.js";
import { setStatus, toast } from "./statusBar.js";

export function initAskPanel() {
  const input = document.getElementById("askInput");
  document.getElementById("askBtn").addEventListener("click", ask);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") ask();
  });
}

async function ask() {
  const input = document.getElementById("askInput");
  const result = document.getElementById("askResult");
  const question = input.value.trim();
  if (!question) return;

  const tracePanel = document.getElementById("askTrace");
  if (tracePanel) tracePanel.hidden = true;
  result.innerHTML = '<div class="loading" style="position:static;background:transparent;"><span class="spinner"></span>检索知识库并回答...</div>';
  setStatus("正在回答知识问题...", "busy");
  try {
    const job = await api("/ask/async", { method: "POST", body: { question, use_database: true } });
    const data = await pollAskJob(job.id);
    const sourceTags = (data.sources || []).map((source) => {
      let label;
      if (source.type === "graph") label = `脉络 · ${source.title || source.id}`;
      else if (source.type === "node") label = `节点 · ${source.label}`;
      else if (source.type === "web") label = `联网 · ${source.title || source.url}`;
      else label = `记忆 · ${source.summary || source.id}`;
      return `<span class="ask-source">${esc(label)}</span>`;
    }).join("");
    const webHint = data.web_fallback_used
      ? '<div class="ask-web-hint">已自动联网搜索补充，请结合来源核实。</div>'
      : "";
    result.innerHTML = `
      <div class="ask-answer markdown-body">${renderMarkdown(data.answer)}</div>
      ${webHint}
      ${sourceTags ? `<div class="ask-sources">${sourceTags}</div>` : '<div class="ask-sources"><span class="ask-source missing">知识库未命中</span></div>'}
    `;
    setStatus("知识问答完成");
  } catch (error) {
    result.innerHTML = `<div class="ask-answer">${esc(error.message)}</div>`;
    toast(error.message, true);
    setStatus("知识问答失败", "error");
  }
}

async function pollAskJob(jobId) {
  for (;;) {
    const job = await api(`/jobs/${encodeURIComponent(jobId)}`);
    renderAgentTrace(job, "askTrace");
    if (job.status === "done") return job.result;
    if (job.status === "error") throw new Error(job.error || "问答失败");
    await new Promise((resolve) => setTimeout(resolve, 600));
  }
}
