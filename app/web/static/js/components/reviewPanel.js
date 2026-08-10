import { api } from "../api.js";
import { esc } from "../util.js";
import { setStatus, toast } from "./statusBar.js";

export function initReviewPanel() {
  refreshReview();
}

export async function refreshReview() {
  try {
    const data = await api("/review");
    const items = data.items || [];
    document.getElementById("reviewDueCount").textContent = `${data.stats.due || 0} 待复习`;
    const el = document.getElementById("reviewList");
    if (!items.length) {
      el.innerHTML = '<div class="empty-state small">今天没有待复习内容</div>';
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
          <button type="button" class="ghost-btn small" data-rating="1">模糊</button>
          <button type="button" class="ghost-btn small" data-rating="2">认识</button>
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
