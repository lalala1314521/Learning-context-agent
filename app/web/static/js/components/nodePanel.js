import { api } from "../api.js";
import { esc, splitIds } from "../util.js";
import { openModal } from "./modal.js";
import { setStatus, toast } from "./statusBar.js";

let currentGraph = null;
let currentNodes = [];
const TYPE_LABELS = {
  concept: "概念",
  method: "方法",
  case: "案例",
  formula: "公式",
  conclusion: "结论",
};

export function initNodePanel() {
  document.getElementById("addNodeBtn").addEventListener("click", addNode);
}

export async function showNodes(data) {
  const graph = data.graph || data;
  currentGraph = graph;
  currentNodes = data.nodes || [];
  document.getElementById("nodeEmpty").hidden = Boolean(currentNodes.length || !graph.id);
  document.getElementById("nodeForm").hidden = !graph.id;
  document.getElementById("nodeList").hidden = currentNodes.length === 0;
  ["nodeCount", "nodeCount2"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.textContent = `${currentNodes.length} 节点`;
  });
  document.getElementById("nodeGraphMeta").textContent = `图: ${graph.id || ""}`;
  renderNodes(currentNodes);
  const highlightId = window.__highlightNode;
  if (highlightId) {
    window.__highlightNode = null;
    const target = document.querySelector(`[data-expand="${highlightId}"]`);
    if (target) {
      const item = target.closest(".node-item");
      item.classList.add("highlight");
      item.scrollIntoView({ block: "nearest" });
      setTimeout(() => item.classList.remove("highlight"), 1800);
    }
  }
  await renderLinks();
}

async function renderLinks() {
  const linksEl = document.getElementById("nodeLinks");
  const existing = document.getElementById("nodeLinks");
  if (existing) existing.remove();
  if (!currentGraph || !currentGraph.id) return;
  try {
    const links = await api(`/links?graph_id=${encodeURIComponent(currentGraph.id)}`);
    if (!links.length) return;
    const byId = new Map(currentNodes.map((node) => [node.id, node]));
    const block = document.createElement("div");
    block.id = "nodeLinks";
    block.className = "link-block";
    block.innerHTML = `<div class="panel-tag">跨脉络关联 ${links.length}</div>` +
      links.map((link) => {
        const outgoing = link.from_graph_id === currentGraph.id;
        const ownLabel = outgoing
          ? (byId.get(link.from_node_id) || {}).label || link.from_node_id
          : (byId.get(link.to_node_id) || {}).label || link.to_node_id;
        const targetGraph = outgoing ? link.to_graph_id : link.from_graph_id;
        const targetLabel = outgoing ? link.to_node_label : link.from_node_label;
        return `
          <div class="link-item" data-graph="${esc(targetGraph)}">
            <div class="link-target">${esc(ownLabel)} → ${esc(targetLabel || "节点")}</div>
            <div class="link-meta">${esc(targetGraph)} · ${esc(link.relation_type || "related")}</div>
          </div>`;
      }).join("");
    block.querySelectorAll(".link-item").forEach((item) => {
      item.addEventListener("click", () => {
        document.dispatchEvent(new CustomEvent("open-graph", { detail: item.dataset.graph }));
      });
    });
    const nodeList = document.getElementById("nodeList");
    nodeList.parentElement.insertBefore(block, nodeList);
  } catch {
    // 链接加载失败不阻塞节点列表
  }
}

function renderNodes(nodes) {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const depth = {};
  const calcDepth = (id) => {
    if (depth[id] !== undefined) return depth[id];
    const node = byId.get(id);
    if (!node || !node.parent_id || !byId.has(node.parent_id)) {
      depth[id] = 0;
      return 0;
    }
    depth[id] = calcDepth(node.parent_id) + 1;
    return depth[id];
  };
  nodes.forEach((node) => calcDepth(node.id));

  const el = document.getElementById("nodeList");
  el.innerHTML = nodes
    .map((node) => {
      const related = (node.related_nodes || [])
        .map((id) => (byId.get(id) ? byId.get(id).label : id))
        .join("、") || "-";
      const parentLabel = node.parent_id && byId.has(node.parent_id)
        ? byId.get(node.parent_id).label
        : "根";
      return `
        <div class="node-item" style="--depth:${Math.min(depth[node.id] || 0, 6)}">
          <div class="node-main" data-expand="${esc(node.id)}">
            <span class="node-label">${esc(node.label)}</span>
            ${(node.concept_mention_count || 0) > 1
              ? `<span class="global-badge" title="该概念还出现在其他材料中">⛓ ${Number(node.concept_mention_count) - 1}</span>`
              : ""}
            <span class="node-type-tag ${esc(node.node_type || "concept")}">${esc(TYPE_LABELS[node.node_type] || "概念")}</span>
            <span class="node-id">${esc(node.id)}</span>
          </div>
          <div class="node-meta">父: ${esc(parentLabel)} · 关联: ${esc(related)}</div>
          <div class="node-note" data-note="${esc(node.id)}" hidden>${esc(node.note || "暂无具体内容，可点击“改”补充。")}</div>
          <div class="node-actions">
            <button type="button" class="ghost-btn small" data-action="update" data-id="${esc(node.id)}">改</button>
            <button type="button" class="ghost-btn small" data-action="relate" data-id="${esc(node.id)}">关联</button>
            <button type="button" class="ghost-btn small danger" data-action="delete" data-id="${esc(node.id)}">删</button>
          </div>
        </div>`;
    })
    .join("");

  el.querySelectorAll("[data-expand]").forEach((row) => {
    row.addEventListener("click", () => {
      const note = el.querySelector(`[data-note="${row.dataset.expand}"]`);
      note.hidden = !note.hidden;
    });
  });
  el.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      handleAction(button.dataset.action, button.dataset.id);
    });
  });
}

function addNode() {
  if (!currentGraph) return;
  const label = document.getElementById("nodeLabelInput").value.trim();
  if (!label) {
    toast("请输入节点文本", true);
    return;
  }
  openModal({
    title: "添加节点",
    fields: [
      { key: "note", label: "具体内容（可选）", type: "textarea", placeholder: "节点展开后显示的内容" },
      { key: "related", label: "关联节点 ID（逗号分隔，可选）" },
    ],
    confirmText: "添加",
    onConfirm: async (values) => {
      await api("/nodes", {
        method: "POST",
        body: {
          graph_id: currentGraph.id,
          label,
          note: values.note || "",
          parent_id: document.getElementById("nodeParentInput").value.trim() || null,
          related_nodes: splitIds(document.getElementById("nodeRelatedInput").value || values.related),
        },
      });
      document.getElementById("nodeLabelInput").value = "";
      document.getElementById("nodeRelatedInput").value = "";
      setStatus("节点已添加");
      await reload();
    },
  });
}

async function handleAction(action, nodeId) {
  const node = currentNodes.find((item) => item.id === nodeId);
  try {
    if (action === "update") {
      openModal({
        title: "编辑节点",
        fields: [
          { key: "label", label: "节点文本", value: node ? node.label : "" },
          { key: "note", label: "具体内容", type: "textarea", value: node ? node.note || "" : "" },
          { key: "type", label: "类型 (concept/method/case/formula/conclusion)", value: node ? node.node_type || "concept" : "concept" },
        ],
        confirmText: "保存",
        onConfirm: async (values) => {
          const body = {};
          if (values.label) body.label = values.label;
          if (values.note !== undefined) body.note = values.note;
          if (values.type) body.node_type = values.type;
          await api(`/nodes/${encodeURIComponent(nodeId)}`, { method: "PATCH", body });
          setStatus("节点已更新");
          await reload();
        },
      });
    } else if (action === "relate") {
      openModal({
        title: "设置关联节点",
        fields: [
          {
            key: "related",
            label: "关联节点 ID（逗号分隔）",
            value: (node && node.related_nodes || []).join(", "),
            placeholder: "同一脉络内的节点 ID",
          },
        ],
        confirmText: "保存",
        onConfirm: async (values) => {
          await api(`/nodes/${encodeURIComponent(nodeId)}`, {
            method: "PATCH",
            body: { related_nodes: splitIds(values.related) },
          });
          setStatus("关联已更新");
          await reload();
        },
      });
    } else if (action === "delete") {
      openModal({
        title: "确认删除",
        fields: [{ key: "message", label: "", value: `确认删除节点「${node ? node.label : nodeId}」？`, type: "textarea" }],
        confirmText: "删除",
        onConfirm: async () => {
          await api(`/nodes/${encodeURIComponent(nodeId)}`, { method: "DELETE" });
          setStatus("节点已删除");
          await reload();
        },
      });
    }
  } catch (error) {
    toast(error.message, true);
  }
}

async function reload() {
  if (!currentGraph) return;
  const data = await api(`/graphs/${encodeURIComponent(currentGraph.id)}`);
  showNodes(data);
}
