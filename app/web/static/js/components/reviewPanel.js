import { api } from "../api.js";
import { esc } from "../util.js";
import { setStatus, toast } from "./statusBar.js";

let currentSession = null;
let currentIndex = 0;

export function initReviewPanel() {
  document.getElementById("startReviewBtn").addEventListener("click", startSession);
  document.getElementById("briefBtn").addEventListener("click", showBrief);
  document.getElementById("weeklyBtn").addEventListener("click", showWeekly);
  refreshReview();
}

export async function refreshReview() {
  try {
    const data = await api("/review");
    const items = data.items || [];
    document.getElementById("reviewDueCount").textContent = `${data.stats.due || 0} 待复习`;
    document.getElementById("reviewDoneCount").textContent = `${data.stats.mastered || 0} 已掌握`;
    const total = data.stats.total || 0;
    const select = document.getElementById("reviewModeSelect");
    ["matching", "feynman", "socratic"].forEach((mode) => {
      const option = select.querySelector(`[value="${mode}"]`);
      if (option) option.disabled = total < 2;
    });
    const crossOption = select.querySelector('[value="cross_doc"]');
    if (crossOption) crossOption.disabled = total < 4;
    const el = document.getElementById("reviewList");
    if (!items.length) {
      el.innerHTML = '<div class="empty-state small">今天没有待复习内容，点击“开始复习”可进行多模式练习</div>';
      return;
    }
    el.innerHTML = items.map((item) => `
      <div class="review-item" data-id="${esc(item.id)}" data-graph-id="${esc(item.graph_id || "")}" data-node-id="${esc(item.node_id || "")}">
        <div class="review-question">${esc(item.question)}</div>
        <div class="review-meta">${esc(item.graph_title || "")} · ${esc(item.node_label || "")}</div>
        <div class="review-answer" hidden>${esc(item.answer)}</div>
        <div class="review-actions">
          <button type="button" class="ghost-btn small" data-answer="1">显示答案</button>
          <button type="button" class="ghost-btn small" data-locate="1">定位</button>
          <button type="button" class="ghost-btn small danger" data-rating="0">忘记</button>
          <button type="button" class="ghost-btn small" data-rating="1">困难</button>
          <button type="button" class="ghost-btn small" data-rating="2">模糊</button>
          <button type="button" class="ghost-btn small" data-rating="3">掌握</button>
        </div>
      </div>`).join("");

    el.querySelectorAll("[data-answer]").forEach((button) => {
      button.addEventListener("click", () => {
        const answer = button.closest(".review-item").querySelector(".review-answer");
        answer.hidden = !answer.hidden;
      });
    });
    el.querySelectorAll("[data-locate]").forEach((button) => {
      button.addEventListener("click", () => {
        const item = button.closest(".review-item");
        document.dispatchEvent(new CustomEvent("open-graph", {
          detail: { graphId: item.dataset.graphId, nodeId: item.dataset.nodeId },
        }));
      });
    });
    el.querySelectorAll("[data-rating]").forEach((button) => {
      button.addEventListener("click", async () => {
        const item = button.closest(".review-item");
        button.disabled = true;
        try {
          await api(`/review/${encodeURIComponent(item.dataset.id)}`, {
            method: "POST",
            body: { rating: Number(button.dataset.rating) },
          });
          setStatus("复习进度已更新");
          document.dispatchEvent(new CustomEvent("review-updated"));
          await refreshReview();
        } catch (error) {
          toast(error.message, true);
          button.disabled = false;
        }
      });
    });
  } catch {
    document.getElementById("reviewList").innerHTML =
      '<div class="empty-state small">复习队列加载失败</div>';
  }
}

async function startSession() {
  const mode = document.getElementById("reviewModeSelect").value || null;
  setStatus("正在准备复习会话...", "busy");
  try {
    const session = await api("/review/session", {
      method: "POST",
      body: { mode, count: 6 },
    });
    currentSession = session;
    currentIndex = 0;
    renderCurrentItem();
    setStatus(`已开始 ${session.mode} 复习`);
  } catch (error) {
    toast(error.message, true);
    setStatus("复习会话创建失败", "error");
  }
}

async function showBrief() {
  setStatus("正在生成今日简报...", "busy");
  try {
    const brief = await api("/review/brief");
    const el = document.getElementById("reviewList");
    el.innerHTML = `
      <div class="review-brief">
        <div class="brief-title">今日知识简报 · ${esc(brief.date)}</div>
        <div class="brief-narrative">${esc(brief.narrative)}</div>
        <div class="brief-concepts">
          ${(brief.concepts || []).map((c) =>
            `<span>${esc(c.label)}</span>`).join("") || "暂无到期概念"}
        </div>
      </div>`;
    setStatus("今日简报已生成");
  } catch (error) {
    toast(error.message, true);
    setStatus("简报生成失败", "error");
  }
}

async function showWeekly() {
  setStatus("正在生成知识周报...", "busy");
  try {
    const [report, achievements] = await Promise.all([
      api("/weekly-report"),
      api("/achievements"),
    ]);
    const el = document.getElementById("reviewList");
    el.innerHTML = `
      <div class="review-brief">
        <div class="brief-title">本周知识网络 · ${esc(report.week_end)}</div>
        <div class="brief-narrative">
          新增 ${report.new_concepts} 个概念、${report.new_links} 条连接；
          当前共 ${report.total_concepts} 个概念，下周预计 ${report.next_week_review_pressure} 次复习。
        </div>
        <div class="brief-concepts">
          ${(report.mastery_top5 || []).map((item) =>
            `<span>${esc(item.label)} · ${item.retrievability ?? "未复习"}</span>`).join("")
            || "暂无掌握度数据"}
        </div>
        <div class="achievement-grid">
          ${(achievements || []).map((item) =>
            `<div class="achievement ${item.unlocked ? "unlocked" : ""}">
               <b>${esc(item.name)}</b>
               <span>${item.unlocked ? "已解锁" : "未解锁"}</span>
             </div>`).join("")}
        </div>
      </div>`;
    setStatus("知识周报已生成");
  } catch (error) {
    toast(error.message, true);
    setStatus("周报生成失败", "error");
  }
}

function renderCurrentItem() {
  const el = document.getElementById("reviewList");
  if (!currentSession) return;
  const item = currentSession.items[currentIndex];
  if (!item) {
    el.innerHTML = '<div class="empty-state small">本轮复习完成，知识网络已刷新</div>';
    currentSession = null;
    document.dispatchEvent(new CustomEvent("review-updated"));
    refreshReview();
    return;
  }
  const html = {
    flashcard: renderFlashcard(item),
    graph_recall: renderGraphRecall(item),
    matching: renderMatching(item),
    feynman: renderFreeText(item),
    socratic: renderFreeText(item),
    cross_doc: renderFreeText(item),
  }[item.type] || renderFreeText(item);
  el.innerHTML = `<div class="review-session-item">${html}</div>`;
  bindItem(item, el.querySelector(".review-session-item"));
}

function renderFlashcard(item) {
  return `
    <div class="review-session-head">闪卡问答</div>
    <div class="review-question">${esc(item.prompt)}</div>
    <div class="review-answer" id="flashcardAnswer" hidden>${esc(item.answer)}</div>
    <div class="review-actions">
      <button type="button" class="ghost-btn small" data-reveal="1">显示答案</button>
      <button type="button" class="ghost-btn small danger" data-rating="0">忘记</button>
      <button type="button" class="ghost-btn small" data-rating="1">困难</button>
      <button type="button" class="ghost-btn small" data-rating="2">模糊</button>
      <button type="button" class="ghost-btn small" data-rating="3">掌握</button>
    </div>`;
}

function renderGraphRecall(item) {
  const graph = item.graph || {};
  return `
    <div class="review-session-head">图回忆 · ${esc(graph.title || "")}</div>
    <div class="review-question">${esc(item.prompt)}</div>
    <div class="recall-nodes">
      ${(graph.nodes || []).map((node) => node.blanked
        ? `<div class="recall-blank">
             <input type="text" data-blank="${esc(node.id)}" placeholder="补全节点内容">
           </div>`
        : `<div class="recall-node">${esc(node.label)}</div>`).join("")}
    </div>
    <div class="review-actions">
      <button type="button" class="primary-btn small" data-submit="1">提交回忆</button>
    </div>`;
}

function renderMatching(item) {
  const pairs = item.pairs || [];
  const rightOptions = [...new Set(pairs.map((p) => p.right))].sort();
  return `
    <div class="review-session-head">连线题</div>
    <div class="review-question">${esc(item.prompt)}</div>
    <div class="matching-grid">
      ${pairs.map((pair, index) => `
        <div class="matching-row">
          <span class="matching-left">${esc(pair.left)}</span>
          <select data-match="${esc(pair.left)}" data-index="${index}">
            <option value="">选择解释</option>
            ${rightOptions.map((right) =>
              `<option value="${esc(right)}">${esc(right)}</option>`).join("")}
          </select>
        </div>`).join("")}
    </div>
    <div class="review-actions">
      <button type="button" class="primary-btn small" data-submit="1">提交连线</button>
    </div>`;
}

function renderFreeText(item) {
  const labels = {
    feynman: "费曼讲述",
    socratic: "苏格拉底追问",
    cross_doc: "跨文档综合",
  };
  return `
    <div class="review-session-head">${labels[item.type] || "自由作答"}</div>
    <div class="review-question">${esc(item.prompt)}</div>
    <textarea id="freeTextAnswer" class="free-text" placeholder="在这里输入你的回答..."></textarea>
    <div class="review-actions">
      <button type="button" class="primary-btn small" data-submit="1">提交回答</button>
    </div>`;
}

function bindItem(item, root) {
  root.querySelector("[data-reveal]")?.addEventListener("click", () => {
    const answer = root.querySelector("#flashcardAnswer");
    if (answer) answer.hidden = !answer.hidden;
  });
  root.querySelectorAll("[data-rating]").forEach((button) => {
    button.addEventListener("click", () =>
      submitAnswer(item, { item_id: item.id, rating: Number(button.dataset.rating) }));
  });
  root.querySelector("[data-submit]")?.addEventListener("click", () => {
    if (item.type === "graph_recall") {
      const answers = {};
      root.querySelectorAll("[data-blank]").forEach((input) => {
        answers[input.dataset.blank] = input.value.trim();
      });
      submitAnswer(item, { item_id: item.id, answers });
    } else if (item.type === "matching") {
      const pairs = {};
      root.querySelectorAll("[data-match]").forEach((select) => {
        pairs[select.dataset.match] = select.value;
      });
      submitAnswer(item, { item_id: item.id, pairs });
    } else {
      const text = root.querySelector("#freeTextAnswer")?.value || "";
      submitAnswer(item, { item_id: item.id, text });
    }
  });
}

async function submitAnswer(item, response) {
  setStatus("正在记录复习结果...", "busy");
  try {
    const result = await api(
      `/review/session/${encodeURIComponent(currentSession.id)}/answer`,
      { method: "POST", body: { response } },
    );
    const el = document.getElementById("reviewList");
    el.innerHTML = `
      <div class="review-feedback">
        <div class="review-session-head">反馈</div>
        <div class="brief-narrative">${esc(result.feedback || "已记录")}</div>
        ${result.answer ? `<div class="review-answer">参考答案：${esc(result.answer)}</div>` : ""}
        <div class="review-actions">
          <button type="button" class="primary-btn small" id="nextReviewBtn">
            ${result.next ? "下一题" : "完成本轮"}
          </button>
        </div>
      </div>`;
    el.querySelector("#nextReviewBtn").addEventListener("click", () => {
      if (result.next) {
        currentIndex = currentSession.items.findIndex((x) => x.id === result.next);
      } else {
        currentIndex = currentSession.items.length;
      }
      renderCurrentItem();
    });
    setStatus("复习结果已记录");
    document.dispatchEvent(new CustomEvent("review-updated"));
  } catch (error) {
    toast(error.message, true);
    setStatus("提交失败", "error");
  }
}
