import { motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { motionOrchestrator } from "../motion";
import type { Graph, GraphDetail, GraphNode } from "../types";

export function KnowledgeScene({ graphs }: { graphs: Graph[] }) {
  const [params] = useSearchParams();
  const [detail, setDetail] = useState<GraphDetail | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const graphId = params.get("graph") || graphs[0]?.id;
  useEffect(() => { if (graphId) api.graph(graphId).then((data) => { setDetail(data); setSelected(data.nodes[0] || null); motionOrchestrator.emit("knowledge.ready", graphId); }).catch(() => setDetail(null)); }, [graphId]);
  if (!graphId) return <div className="panel empty-large"><span className="eyebrow">KNOWLEDGE THREAD</span><h2>还没有可以展开的脉络</h2><p>从材料与生成开始，让第一条主线进入知识空间。</p></div>;
  return <div className="knowledge-layout"><section className="panel graph-panel"><div className="section-heading"><div><span className="eyebrow">KNOWLEDGE THREAD / {detail?.graph.title || "加载中"}</span><h2>主线与关系</h2></div><span className="status-chip">{detail?.nodes.length || 0} 个知识点</span></div>{detail ? <GraphCanvas nodes={detail.nodes} selected={selected?.id} onSelect={(node) => { setSelected(node); motionOrchestrator.emit("concept.focused", node.concept_id || node.id); }} /> : <div className="scene-loading">正在还原结构…</div>}</section><aside className="panel inspector"><span className="eyebrow">INSPECTOR</span>{selected ? <><h3>{selected.label}</h3><span className="type-pill">{selected.node_type || "concept"}</span><p>{selected.note || "这条知识点还没有补充说明。"}</p><div className="evidence-box"><small>原文依据</small><b>{detail?.graph.source_name || "当前材料"}</b><span>选择关系后，这里会显示对应段落和来源定位。</span></div><button className="soft-button">在星图中定位 ↗</button></> : <EmptyInspector />}</aside></div>
}

function GraphCanvas({ nodes, selected, onSelect }: { nodes: GraphNode[]; selected?: string; onSelect: (node: GraphNode) => void }) {
  const positions = useMemo(() => layoutNodes(nodes), [nodes]);
  const byId = new Map(positions.map((node) => [node.id, node]));
  return <div className="graph-scene"><svg viewBox="0 0 900 560" role="img" aria-label="知识脉络图"><defs><linearGradient id="graph-line" x1="0" x2="1"><stop stopColor="var(--accent)" /><stop offset="1" stopColor="var(--cyan)" /></linearGradient><filter id="soft-glow"><feGaussianBlur stdDeviation="5" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter></defs>{positions.flatMap((node) => (node.parent_id && byId.has(node.parent_id) ? [<motion.path key={`line-${node.id}`} className="graph-edge" d={`M ${byId.get(node.parent_id)!.x} ${byId.get(node.parent_id)!.y} C ${(byId.get(node.parent_id)!.x + node.x) / 2} ${byId.get(node.parent_id)!.y}, ${(byId.get(node.parent_id)!.x + node.x) / 2} ${node.y}, ${node.x} ${node.y}`} initial={{ pathLength: 0, opacity: 0 }} animate={{ pathLength: 1, opacity: .55 }} transition={{ duration: .7, delay: .04 * node.depth }} />] : []))}<g className="graph-nodes">{positions.map((node) => <motion.g key={node.id} className={`graph-node ${selected === node.id ? "is-selected" : ""}`} initial={{ opacity: 0, scale: .5 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: .08 * node.depth, duration: .4 }} onClick={() => onSelect(node)} tabIndex={0} role="button" aria-label={node.label}><circle cx={node.x} cy={node.y} r={selected === node.id ? 20 : node.depth === 0 ? 17 : 13} /><circle className="node-core" cx={node.x} cy={node.y} r={selected === node.id ? 7 : 4} /><text x={node.x + 26} y={node.y + 5}>{node.label.length > 18 ? `${node.label.slice(0, 18)}…` : node.label}</text></motion.g>)}</g></svg><div className="graph-legend"><span><i className="legend-dot root" />主线</span><span><i className="legend-dot" />知识点</span><span><i className="legend-line" />证据关系</span></div></div>;
}

function layoutNodes(nodes: GraphNode[]) {
  const children = new Map<string | null, GraphNode[]>(); nodes.forEach((node) => { const key = node.parent_id || null; children.set(key, [...(children.get(key) || []), node]); });
  const result: Array<GraphNode & { x: number; y: number; depth: number }> = [];
  function walk(node: GraphNode, depth: number, index: number, siblings: number) { const x = depth === 0 ? 150 : 270 + depth * 190; const y = depth === 0 ? 280 : 100 + (index + .5) * (360 / Math.max(1, siblings)); result.push({ ...node, x, y, depth }); (children.get(node.id) || []).forEach((child, childIndex, list) => walk(child, depth + 1, childIndex, list.length)); }
  const roots = children.get(null) || nodes.filter((node) => !node.parent_id || !nodes.some((item) => item.id === node.parent_id)); roots.forEach((root, index) => walk(root, 0, index, roots.length)); nodes.filter((node) => !result.some((item) => item.id === node.id)).forEach((node, index) => result.push({ ...node, x: 280, y: 100 + index * 60, depth: 1 })); return result;
}

function EmptyInspector() { return <div className="empty-state"><span className="empty-glyph">⌁</span><p>选择一个知识点查看解释、证据与关系。</p></div>; }
