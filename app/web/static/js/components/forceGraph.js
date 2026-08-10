import { esc } from "../util.js";
import { showNodeDetails } from "./nodePanel.js";

let simulation = null;

const TYPE_COLORS = {
  concept: "#4A8DFF",
  method: "#10B981",
  case: "#FF7A45",
  formula: "#7B5CD6",
  conclusion: "#6B7280",
};

const TYPE_LABELS = {
  concept: "概念",
  method: "方法",
  case: "案例",
  formula: "公式",
  conclusion: "结论",
};

export function renderForceGraph(graph, nodes, links, conceptLinks = []) {
  const area = document.getElementById("forceArea");
  area.hidden = false;
  area.innerHTML = "";
  if (!window.d3) {
    area.innerHTML = '<div class="empty-state">力导向图谱组件未加载</div>';
    return;
  }

  const width = area.clientWidth || 700;
  const height = area.clientHeight || 480;
  const svg = window.d3.select(area).append("svg");
  const defs = svg.append("defs");
  const linkLayer = svg.append("g");
  const nodeLayer = svg.append("g");

  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const related = [];
  nodes.forEach((node) => {
    if (node.parent_id && nodeMap.has(node.parent_id) && node.id !== node.parent_id) {
      related.push({ source: node.id, target: node.parent_id });
    }
    (node.related_nodes || []).forEach((targetId) => {
      if (nodeMap.has(targetId) && node.id !== targetId) {
        related.push({ source: node.id, target: targetId });
      }
    });
  });
  (links || []).forEach((link) => {
    if (link.from_graph_id === graph.id && nodeMap.has(link.from_node_id) && nodeMap.has(link.to_node_id)) {
      related.push({ source: link.from_node_id, target: link.to_node_id });
    }
  });
  const conceptToNodes = new Map();
  nodes.forEach((node) => {
    if (!node.concept_id) return;
    if (!conceptToNodes.has(node.concept_id)) conceptToNodes.set(node.concept_id, []);
    conceptToNodes.get(node.concept_id).push(node.id);
  });
  (conceptLinks || []).forEach((link) => {
    const fromNodes = conceptToNodes.get(link.from_concept) || [];
    const toNodes = conceptToNodes.get(link.to_concept) || [];
    fromNodes.forEach((fromNode) => {
      toNodes.forEach((toNode) => {
        if (fromNode !== toNode) {
          related.push({ source: fromNode, target: toNode });
        }
      });
    });
  });
  const seen = new Set();
  const uniqueLinks = related.filter((link) => {
    const key = [link.source, link.target].sort().join("|");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  const linkSelection = linkLayer.selectAll("line")
    .data(uniqueLinks)
    .enter()
    .append("line")
    .attr("class", "force-link");

  const nodeSelection = nodeLayer.selectAll("g")
    .data(nodes)
    .enter()
    .append("g")
    .attr("class", "force-node")
    .call(window.d3.drag()
      .on("start", (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on("end", (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      }));

  nodeSelection.each(function (d) {
    const g = window.d3.select(this);
    g.append("circle")
      .attr("r", 24)
      .attr("fill", TYPE_COLORS[d.node_type] || TYPE_COLORS.concept)
      .attr("opacity", 0.14);
    g.append("circle")
      .attr("r", 16)
      .attr("fill", TYPE_COLORS[d.node_type] || TYPE_COLORS.concept);
    g.append("text")
      .attr("dy", 4)
      .text((node) => (node.label && node.label.length > 6 ? node.label.slice(0, 6) + "…" : node.label));
    g.append("title").text((node) => `${node.label}\n${TYPE_LABELS[node.node_type] || "概念"}\n${node.note || ""}`);
  });

  simulation = window.d3.forceSimulation(nodes)
    .force("link", window.d3.forceLink(uniqueLinks).id((d) => d.id).distance(110))
    .force("charge", window.d3.forceManyBody().strength(-260))
    .force("center", window.d3.forceCenter(width / 2, height / 2))
    .force("collide", window.d3.forceCollide(42))
    .on("tick", () => {
      linkSelection
        .attr("x1", (d) => d.source.x)
        .attr("y1", (d) => d.source.y)
        .attr("x2", (d) => d.target.x)
        .attr("y2", (d) => d.target.y);
      nodeSelection.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });

  nodeSelection.on("click", (event, d) => {
    if (d.note) {
      const tip = area.querySelector(".force-tip");
      const existing = tip || document.createElement("div");
      existing.className = "force-tip";
      existing.innerHTML = `<b>${esc(d.label)}</b><span>${esc(d.note)}</span>`;
      if (!tip) area.appendChild(existing);
      setTimeout(() => existing.remove(), 5000);
    }
  });
  // 双击节点 → 展开完整知识点详情
  nodeSelection.on("dblclick", (event, d) => {
    event.stopPropagation();
    showNodeDetails(d);
  });
}

export function destroyForceGraph() {
  if (simulation) {
    simulation.stop();
    simulation = null;
  }
  const area = document.getElementById("forceArea");
  if (area) area.innerHTML = "";
}
