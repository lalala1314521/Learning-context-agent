import { useEffect, useMemo, useState } from "react";
import { Handle, MarkerType, MiniMap, Position, ReactFlow, useEdgesState, useNodesState, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { motionOrchestrator } from "../motion";
import type { Graph, GraphDetail, GraphNode } from "../types";

type FlowData = { label: string; note?: string; nodeType?: string; selected?: boolean; onSelect: () => void };
type FlowNode = Node<FlowData>;

export function KnowledgeScene({ graphs }: { graphs: Graph[] }) {
  const [params] = useSearchParams();
  const [detail, setDetail] = useState<GraphDetail | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const graphId = params.get("graph") || graphs[0]?.id;
  useEffect(() => { if (graphId) api.graph(graphId).then((data) => { setDetail(data); setSelected(data.nodes[0] || null); motionOrchestrator.emit("knowledge.ready", graphId); }).catch(() => setDetail(null)); }, [graphId]);
  if (!graphId) return <div className="panel empty-large"><span className="eyebrow">KNOWLEDGE THREAD</span><h2>还没有可以展开的脉络</h2><p>从材料与生成开始，让第一条主线进入知识空间。</p></div>;
  return <div className="knowledge-layout"><section className="panel graph-panel"><div className="section-heading"><div><span className="eyebrow">KNOWLEDGE THREAD / {detail?.graph.title || "加载中"}</span><h2>主线与关系</h2></div><span className="status-chip">{detail?.nodes.length || 0} 个知识点</span></div>{detail ? <GraphCanvas nodes={detail.nodes} links={detail.links || detail.structure?.edges || []} selected={selected?.id} onSelect={(node) => { setSelected(node); motionOrchestrator.emit("concept.focused", node.concept_id || node.id); }} /> : <div className="scene-loading">正在还原结构…</div>}</section><aside className="panel inspector"><span className="eyebrow">INSPECTOR</span>{selected ? <><h3>{selected.label}</h3><span className="type-pill">{selected.node_type || "concept"}</span><p>{selected.note || "这条知识点还没有补充说明。"}</p><div className="evidence-box"><small>原文依据</small><b>{detail?.graph.source_name || "当前材料"}</b><span>选择关系后，这里会显示对应段落和来源定位。</span></div><Link className="soft-button" to={`/galaxy?concept=${encodeURIComponent(selected.concept_id || selected.label)}`}>在星图中定位 ↗</Link></> : <EmptyInspector />}</aside></div>;
}

function GraphCanvas({ nodes, links, selected, onSelect }: { nodes: GraphNode[]; links: Array<{ id?: string; from_node_id?: string; to_node_id?: string; source?: string; target?: string; relation_type?: string }>; selected?: string; onSelect: (node: GraphNode) => void }) {
  const [flowNodes, setFlowNodes] = useNodesState<FlowNode>([]);
  const [flowEdges, setFlowEdges] = useEdgesState<Edge>([]);
  const nodeTypes = useMemo(() => ({ knowledge: KnowledgeNode }), []);
  useEffect(() => {
    let cancelled = false;
    const rawNodes = nodes.map((node) => ({ id: node.id, width: 190, height: 70 }));
    const rawEdges = links.map((link, index) => ({ id: link.id || `edge-${index}`, sources: [link.from_node_id || link.source || ""], targets: [link.to_node_id || link.target || ""] })).filter((edge) => edge.sources[0] && edge.targets[0]);
    import("elkjs/lib/elk.bundled.js").then(({ default: ELK }) => new ELK().layout({ id: "knowledge", layoutOptions: { "elk.algorithm": "layered", "elk.direction": "RIGHT", "elk.spacing.nodeNode": "38", "elk.layered.spacing.nodeNodeBetweenLayers": "110" }, children: rawNodes, edges: rawEdges })).then((layout) => {
      if (cancelled) return;
      const positions = new Map((layout.children || []).map((child) => [child.id, { x: child.x || 0, y: child.y || 0 }]));
      setFlowNodes(nodes.map((node) => ({ id: node.id, type: "knowledge", position: positions.get(node.id) || { x: 0, y: 0 }, data: { label: node.label, note: node.note, nodeType: node.node_type, selected: selected === node.id, onSelect: () => onSelect(node) } })));
      setFlowEdges(rawEdges.map((edge, index) => ({ id: edge.id, source: edge.sources[0], target: edge.targets[0], label: links[index]?.relation_type || "", markerEnd: { type: MarkerType.ArrowClosed, color: "#74e4d2" }, className: "knowledge-edge", animated: selected === edge.sources[0] || selected === edge.targets[0] })));
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [nodes, links, selected, onSelect, setFlowEdges, setFlowNodes]);
  return <div className="graph-scene flow-scene"><ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: .24 }} minZoom={.35} maxZoom={1.5} nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }}><MiniMap nodeColor={(node) => node.id === selected ? "#74e4d2" : "#9bb2ff"} /><div className="graph-legend"><span><i className="legend-dot root" />主线</span><span><i className="legend-dot" />知识点</span><span><i className="legend-line" />证据关系</span></div></ReactFlow></div>;
}

function KnowledgeNode({ data, selected }: NodeProps<FlowNode>) {
  return <div className={`knowledge-flow-node ${selected || data.selected ? "is-selected" : ""}`} onClick={data.onSelect} role="button" tabIndex={0}><Handle type="target" position={Position.Left} /><span className="flow-node-kind">{data.nodeType || "concept"}</span><strong>{data.label}</strong><Handle type="source" position={Position.Right} /></div>;
}

function EmptyInspector() { return <div className="empty-state"><span className="empty-glyph">⌁</span><p>选择一个知识点查看解释、证据与关系。</p></div>; }
