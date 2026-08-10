import { api } from "../api.js";
import { esc } from "../util.js";
import { toast } from "./statusBar.js";

let galaxyCache = null;
let simulation = null;
let startId = null;
let endId = null;
let pathIds = new Set();
let mode = null;

const MASTERY = {
  unseen: { color: "#9CA3AF", label: "未复习" },
  weak: { color: "#F87171", label: "遗忘" },
  medium: { color: "#FBBF24", label: "模糊" },
  strong: { color: "#34D399", label: "牢固" },
};

export function initGalaxyPanel() {
  document.getElementById("pathStartBtn").addEventListener("click", () => {
    mode = "start";
    setStatus("请点击星图选择一个起点概念");
  });
  document.getElementById("pathEndBtn").addEventListener("click", () => {
    mode = "end";
    setStatus("请点击星图选择一个终点概念");
  });
  document.getElementById("pathExplainBtn").addEventListener("click", explainPath);
  showGalaxy();
}

export async function showGalaxy(force = false) {
  const area = document.getElementById("galaxyArea");
  if (!area) return;
  area.hidden = false;
  const viewport = document.getElementById("viewport");
  const forceArea = document.getElementById("forceArea");
  const outline = document.getElementById("outlineArea");
  if (viewport) viewport.hidden = true;
  if (forceArea) forceArea.hidden = true;
  if (outline) outline.hidden = true;
  if (!galaxyCache || force) {
    try {
      galaxyCache = await api("/galaxy");
    } catch (error) {
      area.innerHTML = `<div class="empty-state small">星图加载失败：${esc(error.message)}</div>`;
      return;
    }
  }
  render();
}

export async function refreshGalaxy() {
  galaxyCache = null;
  pathIds.clear();
  startId = null;
  endId = null;
  mode = null;
  await showGalaxy(true);
}

function render() {
  const canvas = document.getElementById("galaxyCanvas");
  if (!canvas) return;
  if (!window.d3) {
    canvas.innerHTML = '<div class="empty-state">D3 未加载，无法渲染星图</div>';
    return;
  }
  stopSimulation();
  canvas.innerHTML = "";

  const width = canvas.clientWidth || 900;
  const height = canvas.clientHeight || 560;
  const svg = window.d3.select(canvas).append("svg");
  const inner = svg.append("g");
  const domainLayer = inner.append("g").attr("class", "galaxy-domain-layer");
  const linkLayer = inner.append("g").attr("class", "galaxy-link-layer");
  const nodeLayer = inner.append("g").attr("class", "galaxy-node-layer");

  const concepts = (galaxyCache.concepts || []).map((c) => ({
    ...c,
    degree: 0,
    x: width / 2 + (Math.random() - 0.5) * 80,
    y: height / 2 + (Math.random() - 0.5) * 80,
  }));
  const conceptIds = new Set(concepts.map((c) => c.id));
  const links = (galaxyCache.links || [])
    .filter((l) => conceptIds.has(l.from_concept) && conceptIds.has(l.to_concept))
    .map((l) => ({ ...l, source: l.from_concept, target: l.to_concept }));
  links.forEach((l) => {
    const from = concepts.find((c) => c.id === l.source);
    const to = concepts.find((c) => c.id === l.target);
    if (from) from.degree += 1;
    if (to) to.degree += 1;
  });

  const domains = galaxyCache.domains || [];
  const domainMap = new Map(domains.map((d) => [d.id, d]));
  const domainBubbles = domains.map((d) => ({
    ...d,
    x: width / 2,
    y: height / 2,
  }));

  const linkSelection = linkLayer.selectAll("line")
    .data(links)
    .enter()
    .append("line")
    .attr("class", "galaxy-link")
    .attr("stroke-width", (d) => 0.6 + Math.min(2.2, Number(d.confidence || 0) * 2))
    .attr("stroke-dasharray", (d) =>
      d.status === "pending" || Number(d.confidence || 0) < 0.8 ? "4 4" : null)
    .attr("opacity", (d) => 0.35 + Math.min(0.45, Number(d.confidence || 0)));

  const nodeSelection = nodeLayer.selectAll("g")
    .data(concepts)
    .enter()
    .append("g")
    .attr("class", "galaxy-node")
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

  const radius = (d) => 9 + Math.min(18, Math.log2((d.degree || 0) + (d.mention_count || 0) + 2) * 3.2);
  const domainColor = (d) => {
    const domain = domainMap.get(d.domain_id);
    return (domain && domain.color) || "#64748B";
  };

  nodeSelection.each(function (d) {
    const g = window.d3.select(this);
    const r = radius(d);
    const mastery = MASTERY[(d.mastery && d.mastery.mastery) || "unseen"] || MASTERY.unseen;
    const selected = pathIds.has(d.id);
    g.append("circle")
      .attr("class", "galaxy-glow")
      .attr("r", r + 7)
      .attr("fill", mastery.color)
      .attr("opacity", 0.2);
    g.append("circle")
      .attr("class", "galaxy-core")
      .attr("r", r)
      .attr("fill", domainColor(d))
      .attr("stroke", selected ? "#F59E0B" : "#ffffff")
      .attr("stroke-width", selected ? 3 : 1.5);
    g.append("text")
      .attr("class", "galaxy-label")
      .attr("dy", 4)
      .attr("opacity", 1)
      .text((node) => (node.canonical_label || "").slice(0, 7));
    g.append("title").text((node) =>
      `${node.canonical_label || ""}\n领域: ${domainMap.get(node.domain_id)?.name || "未分类"}\n`
      + `掌握度: ${mastery.label} · 提及: ${node.mention_count || 0}\n`
      + `摘要: ${node.summary || ""}`);
  });

  const domainSelection = domainLayer.selectAll("g")
    .data(domainBubbles)
    .enter()
    .append("g")
    .attr("class", "galaxy-domain");
  domainSelection.each(function (d) {
    const g = window.d3.select(this);
    g.append("circle")
      .attr("r", 42)
      .attr("fill", d.color)
      .attr("opacity", 0.12);
    g.append("text")
      .attr("dy", 4)
      .attr("text-anchor", "middle")
      .attr("fill", d.color)
      .text((domain) => domain.name.slice(0, 6));
  });

  simulation = window.d3.forceSimulation(concepts)
    .force("link", window.d3.forceLink(links).id((d) => d.id).distance(130))
    .force("charge", window.d3.forceManyBody().strength(-320))
    .force("center", window.d3.forceCenter(width / 2, height / 2))
    .force("collide", window.d3.forceCollide().radius((d) => radius(d) + 16))
    .on("tick", () => {
      linkSelection
        .attr("x1", (d) => d.source.x)
        .attr("y1", (d) => d.source.y)
        .attr("x2", (d) => d.target.x)
        .attr("y2", (d) => d.target.y);
      nodeSelection.attr("transform", (d) => `translate(${d.x},${d.y})`);
      domainSelection.attr("transform", (d) => {
        const members = concepts.filter((c) => c.domain_id === d.id);
        if (!members.length) return `translate(${width / 2},${height / 2})`;
        const cx = members.reduce((sum, c) => sum + c.x, 0) / members.length;
        const cy = members.reduce((sum, c) => sum + c.y, 0) / members.length;
        return `translate(${cx},${cy})`;
      });
    });

  const zoom = window.d3.zoom()
    .scaleExtent([0.25, 3])
    .on("zoom", (event) => {
      inner.attr("transform", event.transform);
      const scale = event.transform.k;
      nodeSelection.selectAll(".galaxy-label")
        .attr("opacity", scale < 0.7 ? 0 : 1);
      domainLayer.attr("opacity", scale < 0.8 ? 1 : 0.15);
    });
  svg.call(zoom);

  nodeSelection
    .on("click", (event, d) => {
      event.stopPropagation();
      if (mode === "start") {
        startId = d.id;
        mode = null;
        setStatus(`起点已选：${d.canonical_label}`);
        document.getElementById("pathStartBtn").textContent = `起点: ${d.canonical_label.slice(0, 6)}`;
      } else if (mode === "end") {
        endId = d.id;
        mode = null;
        setStatus(`终点已选：${d.canonical_label}`);
        document.getElementById("pathEndBtn").textContent = `终点: ${d.canonical_label.slice(0, 6)}`;
      } else {
        highlightNeighbors(d, concepts, links);
      }
    })
    .on("dblclick", async (event, d) => {
      event.stopPropagation();
      await showConceptDetail(d.id);
    });

  svg.on("click", () => {
    if (mode) {
      mode = null;
      setStatus("已取消选择");
    }
  });
  document.getElementById("galaxyCount").textContent =
    `${concepts.length} 概念 · ${links.length} 边`;
}

function highlightNeighbors(center, concepts, links) {
  const neighborIds = new Set([center.id]);
  links.forEach((l) => {
    if (l.source === center.id || l.source.id === center.id) {
      neighborIds.add(typeof l.target === "object" ? l.target.id : l.target);
    }
    if (l.target === center.id || l.target.id === center.id) {
      neighborIds.add(typeof l.source === "object" ? l.source.id : l.source);
    }
  });
  window.d3.selectAll(".galaxy-node")
    .attr("opacity", (d) => neighborIds.has(d.id) ? 1 : 0.18);
  window.d3.selectAll(".galaxy-link")
    .attr("opacity", (d) => {
      const a = typeof d.source === "object" ? d.source.id : d.source;
      const b = typeof d.target === "object" ? d.target.id : d.target;
      return neighborIds.has(a) && neighborIds.has(b) ? 0.9 : 0.08;
    });
}

async function explainPath() {
  if (!startId || !endId) {
    toast("请先选择起点和终点", true);
    return;
  }
  setStatus("正在生成知识链路...", "busy");
  try {
    const data = await api(`/concepts/${startId}/path/${endId}`);
    pathIds = new Set((data.path || []).map((c) => c.id));
    render();
    const result = document.getElementById("galaxyPathResult");
    result.hidden = false;
    result.innerHTML = `
      <div class="path-heading">知识链路</div>
      <div class="path-labels">${(data.path || []).map((c) => esc(c.canonical_label)).join(" → ")}</div>
      <div class="path-explanation">${esc(data.explanation || "")}</div>`;
    setStatus("知识链路已生成");
  } catch (error) {
    toast(error.message, true);
    setStatus("知识链路生成失败", "error");
  }
}

async function showConceptDetail(conceptId) {
  try {
    const data = await api(`/concepts/${encodeURIComponent(conceptId)}`);
    const concept = data.concept || {};
    const result = document.getElementById("galaxyPathResult");
    result.hidden = false;
    result.innerHTML = `
      <div class="path-heading">概念详情</div>
      <div class="concept-detail-title">${esc(concept.canonical_label || "")}</div>
      <div class="concept-detail-summary">${esc(concept.summary || "暂无摘要")}</div>
      <div class="concept-detail-mentions">
        ${(data.mentions || []).map((m) =>
          `<span>${esc(m.graph_title || "脉络")} · ${esc(m.label)}</span>`).join("") || "暂无提及"}
      </div>`;
  } catch (error) {
    toast(error.message, true);
  }
}

function setStatus(message) {
  const el = document.getElementById("pathStatus");
  if (el) el.textContent = message;
}

function stopSimulation() {
  if (simulation) {
    simulation.stop();
    simulation = null;
  }
}
