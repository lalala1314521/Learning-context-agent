import { api } from "../api.js";
import { esc } from "../util.js";
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

  result.innerHTML = '<div class="loading" style="position:static;background:transparent;"><span class="spinner"></span>检索知识库并回答...</div>';
  setStatus("正在回答知识问题...", "busy");
  try {
    const data = await api("/ask", { method: "POST", body: { question, use_database: true } });
    const sourceTags = (data.sources || []).map((source) => {
      const label = source.type === "graph"
        ? `脉络 · ${source.title || source.id}`
        : source.type === "node"
          ? `节点 · ${source.label}`
          : `记忆 · ${source.summary || source.id}`;
      return `<span class="ask-source">${esc(label)}</span>`;
    }).join("");
    result.innerHTML = `
      <div class="ask-answer">${esc(data.answer)}</div>
      ${sourceTags ? `<div class="ask-sources">${sourceTags}</div>` : '<div class="ask-sources"><span class="ask-source missing">知识库未命中</span></div>'}
    `;
    setStatus("知识问答完成");
  } catch (error) {
    result.innerHTML = `<div class="ask-answer">${esc(error.message)}</div>`;
    toast(error.message, true);
    setStatus("知识问答失败", "error");
  }
}
