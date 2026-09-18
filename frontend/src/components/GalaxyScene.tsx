import { useEffect, useRef, useState } from "react";
import { Application, Container, Graphics, Text, TextStyle } from "pixi.js";
import { motionOrchestrator } from "../motion";
import { api } from "../api";
import type { Concept, ConceptLink, Domain, GalaxyData } from "../types";

type Point = { id: string; label: string; domainId?: string | null; x: number; y: number; radius: number; color: number; labelVisible: boolean };

export function GalaxyScene() {
  const searchRef = useRef<HTMLInputElement>(null);
  const [data, setData] = useState<GalaxyData | null>(null);
  const [selected, setSelected] = useState<Concept | null>(null);
  const [query, setQuery] = useState("");
  const [focusId, setFocusId] = useState("");
  const [zoom, setZoom] = useState(1);
  useEffect(() => { api.galaxy().then((payload) => { setData(payload); motionOrchestrator.emit("scene.entered", "galaxy"); }).catch(() => setData({ concepts: [], links: [], domains: [] })); }, []);
  useEffect(() => { const onKey = (event: KeyboardEvent) => { if (event.key === "/" && document.activeElement?.tagName !== "INPUT") { event.preventDefault(); searchRef.current?.focus(); } if (event.key === "Escape") { setQuery(""); setFocusId(""); searchRef.current?.blur(); } }; window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, []);
  const compact = data ? compressGalaxy(data) : null;
  const displayData = compact && query.trim() ? { ...compact, concepts: compact.concepts.filter((concept) => concept.canonical_label.toLowerCase().includes(query.trim().toLowerCase())) } : compact;
  const selectConcept = (concept: Concept) => { setSelected(concept); setFocusId(concept.id); motionOrchestrator.emit("concept.focused", concept.id); };
  return <div className="galaxy-layout"><section className="panel galaxy-panel"><div className="section-heading"><div><span className="eyebrow">GLOBAL KNOWLEDGE SPACE</span><h2>让概念彼此找到</h2></div><div className="galaxy-tools"><span className="status-chip">{data?.concepts.length || 0} 概念</span><button className="icon-button" title="缩小镜头" onClick={() => setZoom((value) => Math.max(.65, value - .15))}>−</button><button className="icon-button" title="放大镜头" onClick={() => setZoom((value) => Math.min(1.8, value + .15))}>＋</button><button className="icon-button" title="重置镜头" onClick={() => { setZoom(1); setFocusId(""); setQuery(""); motionOrchestrator.emit("scene.entered", "galaxy-reset"); }}>◎</button></div></div><div className="galaxy-search"><span>⌕</span><input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && displayData?.concepts[0]) { selectConcept(displayData.concepts[0]); } }} placeholder="搜索概念，定位局部关系（/ 聚焦）" /><small>{query ? `${displayData?.concepts.length || 0} 个匹配` : "总览"}</small></div><div className="galaxy-stage">{displayData ? <PixiGalaxy data={displayData} zoom={zoom} focusId={focusId} selectedId={selected?.id} onSelect={selectConcept} /> : <div className="scene-loading">正在铺开领域与关系…</div>}<div className="galaxy-overlay"><span><i className="legend-dot root" />领域光场</span><span><i className="legend-dot" />概念</span><span><i className="legend-line" />真实关系</span></div></div></section><aside className="panel galaxy-inspector"><span className="eyebrow">CONCEPT SIGNAL</span>{selected ? <><h3>{selected.canonical_label}</h3><p>{selected.description || "这个概念还没有摘要。"}</p><div className="signal-card"><small>来自材料</small><strong>{selected.mention_count || 0} 次提及</strong></div><div className="signal-card"><small>掌握状态</small><strong>{selected.mastery?.mastery || "未复习"}</strong></div><button className="soft-button" onClick={() => setFocusId(selected.id)}>展开邻域 ↗</button></> : <div className="empty-state"><span className="empty-glyph">✺</span><p>点击星体，查看概念来源、关系和学习信号。</p></div>}</aside></div>;
}

function compressGalaxy(data: GalaxyData): GalaxyData {
  const topDomains = [...data.domains].sort((a, b) => (b.concept_count || 0) - (a.concept_count || 0)).slice(0, 12);
  const topIds = new Set(topDomains.map((domain) => domain.id));
  const otherConcepts = data.concepts.filter((concept) => concept.domain_id && !topIds.has(concept.domain_id));
  const domains = [...topDomains];
  if (otherConcepts.length) domains.push({ id: "other", name: "其他领域", color: "#7180ad", concept_count: otherConcepts.length });
  return { ...data, domains, concepts: data.concepts.map((concept) => ({ ...concept, domain_id: concept.domain_id && topIds.has(concept.domain_id) ? concept.domain_id : (otherConcepts.length ? "other" : concept.domain_id) })) };
}

function PixiGalaxy({ data, zoom, focusId, selectedId, onSelect }: { data: GalaxyData; zoom: number; focusId?: string; selectedId?: string; onSelect: (concept: Concept) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!host.current) return;
    let disposed = false;
    const app = new Application();
    const root = host.current;
    app.init({ resizeTo: root, backgroundAlpha: 0, antialias: true, resolution: Math.min(window.devicePixelRatio || 1, 2) }).then(() => {
      if (disposed) return;
      root.appendChild(app.canvas);
      const scene = new Container(); scene.scale.set(zoom); app.stage.addChild(scene);
      const width = root.clientWidth || 700; const height = root.clientHeight || 520;
      const points = project(data.concepts, data.domains, width / zoom, height / zoom);
      const byId = new Map(points.map((point) => [point.id, point]));
      const focusIds = focusId ? new Set([focusId, ...data.links.flatMap((link) => link.from_concept === focusId ? [link.to_concept] : link.to_concept === focusId ? [link.from_concept] : [])]) : null;

      // 七层场景：背景、光场、关系、领域、星体、标签、焦点。每层只负责一种语义。
      const backgroundLayer = new Graphics().rect(0, 0, width / zoom, height / zoom).fill({ color: 0x080d1d, alpha: .24 });
      const fieldLayer = new Container();
      const relationLayer = new Graphics();
      const domainLayer = new Graphics();
      const starLayer = new Container();
      const labelLayer = new Container();
      const focusLayer = new Container();
      scene.addChild(backgroundLayer, fieldLayer, relationLayer, domainLayer, starLayer, labelLayer, focusLayer);

      for (let index = 0; index < 12; index += 1) {
        const glow = new Graphics().circle((width / zoom) * ((index * 37) % 100) / 100, (height / zoom) * ((index * 61) % 100) / 100, 22 + (index % 4) * 12).fill({ color: index % 2 ? 0x74e4d2 : 0x6383d9, alpha: .025 });
        fieldLayer.addChild(glow);
      }

      data.links.forEach((link) => {
        const from = byId.get(link.from_concept); const to = byId.get(link.to_concept);
        if (!from || !to) return;
        const active = !focusIds || focusIds.has(link.from_concept) || focusIds.has(link.to_concept);
        relationLayer.moveTo(from.x, from.y).bezierCurveTo((from.x + to.x) / 2, from.y - 22, (from.x + to.x) / 2, to.y + 22, to.x, to.y).stroke({ color: 0x6383d9, alpha: active ? .42 : .06, width: active ? 1.7 : 1 });
      });

      const labelStyle = new TextStyle({ fontFamily: "Microsoft YaHei, sans-serif", fontSize: 12, fill: 0xdbe7ff, fontWeight: "500" });
      const domainStyle = new TextStyle({ fontFamily: "Microsoft YaHei, sans-serif", fontSize: 11, fill: 0x9aa9d5, fontWeight: "700" });
      data.domains.forEach((domain) => {
        const domainPoints = points.filter((point) => point.domainId === domain.id); if (!domainPoints.length) return;
        const minX = Math.min(...domainPoints.map((point) => point.x)) - 32; const maxX = Math.max(...domainPoints.map((point) => point.x)) + 32; const minY = Math.min(...domainPoints.map((point) => point.y)) - 32; const maxY = Math.max(...domainPoints.map((point) => point.y)) + 32;
        const color = Number((domain.color || "#596fae").replace("#", "0x"));
        domainLayer.roundRect(minX, minY, maxX - minX, maxY - minY, 26).fill({ color, alpha: .045 }).stroke({ color, alpha: .24, width: 1 });
        const title = new Text({ text: domain.name, style: domainStyle }); title.x = minX + 15; title.y = minY + 12; labelLayer.addChild(title);
      });

      points.forEach((point) => {
        const active = !focusIds || focusIds.has(point.id); const concept = data.concepts.find((item) => item.id === point.id); if (!concept) return;
        const star = new Graphics().circle(point.x, point.y, point.radius).fill({ color: point.color, alpha: active ? .94 : .16 });
        star.circle(point.x, point.y, point.radius + (selectedId === point.id ? 10 : 7)).stroke({ color: point.color, alpha: selectedId === point.id ? .55 : active ? .12 : .03, width: selectedId === point.id ? 2 : 1 });
        star.eventMode = "static"; star.cursor = "pointer"; star.on("pointertap", () => onSelect(concept)); starLayer.addChild(star);
        if (point.labelVisible || focusIds?.has(point.id)) { const label = new Text({ text: point.label, style: labelStyle }); label.alpha = active ? 1 : .2; label.x = point.x + point.radius + 7; label.y = point.y - 7; labelLayer.addChild(label); }
      });

      if (selectedId) {
        const selectedPoint = byId.get(selectedId);
        if (selectedPoint) { const pulse = new Graphics().circle(selectedPoint.x, selectedPoint.y, selectedPoint.radius + 14).stroke({ color: 0x74e4d2, alpha: .32, width: 1.5 }); focusLayer.addChild(pulse); let phase = 0; app.ticker.add((ticker) => { phase += ticker.deltaTime * .035; pulse.scale.set(1 + Math.sin(phase) * .08); pulse.alpha = .22 + (Math.sin(phase) + 1) * .08; fieldLayer.alpha = .82 + Math.sin(phase * .4) * .08; }); }
      }
      setReady(true);
    });
    return () => { disposed = true; app.destroy(true, { children: true }); root.replaceChildren(); };
  }, [data, focusId, onSelect, selectedId, zoom]);
  return <div ref={host} className={`pixi-host ${ready ? "is-ready" : ""}`} aria-label="全局知识星图" />;
}

function project(concepts: Concept[], domains: Domain[], width: number, height: number): Point[] {
  const palette = ["#87a7ff", "#e89b68", "#79d5bd", "#c58bdf", "#f2cc72"];
  const grouped = new Map<string, Concept[]>(); concepts.forEach((concept) => { const key = concept.domain_id || "unassigned"; grouped.set(key, [...(grouped.get(key) || []), concept]); });
  grouped.forEach((members, key) => grouped.set(key, [...members].sort((a, b) => (b.mention_count || 0) - (a.mention_count || 0))));
  const labelIds = new Set([...concepts].sort((a, b) => (b.mention_count || 0) - (a.mention_count || 0)).slice(0, 12).map((concept) => concept.id));
  const domainKeys = [...grouped.keys()]; const anchors = new Map<string, { x: number; y: number; color: number }>(); const columns = Math.max(1, Math.ceil(Math.sqrt(domainKeys.length)));
  domainKeys.forEach((key, index) => { const row = Math.floor(index / columns); const col = index % columns; const x = width * .18 + col * (width * .64 / Math.max(1, columns - 1)); const y = height * .2 + row * (height * .58 / Math.max(1, Math.ceil(domainKeys.length / columns) - 1 || 1)); const domainIndex = Math.max(0, domains.findIndex((domain) => domain.id === key)); anchors.set(key, { x: columns === 1 ? width / 2 : x, y: domainKeys.length === 1 ? height / 2 : y, color: Number((domains[domainIndex]?.color || palette[index % palette.length]).replace("#", "0x")) }); });
  return concepts.map((concept) => { const key = concept.domain_id || "unassigned"; const anchor = anchors.get(key) || { x: width / 2, y: height / 2, color: 0x87a7ff }; const peers = grouped.get(key) || []; const peerIndex = peers.findIndex((peer) => peer.id === concept.id); const angle = peerIndex * 2.399963 + (key.length % 5) * .4; const radius = 18 + Math.sqrt(peerIndex + 1) * 17; return { id: concept.id, label: concept.canonical_label, domainId: concept.domain_id, x: anchor.x + Math.cos(angle) * Math.min(width * .24, radius * 2.2), y: anchor.y + Math.sin(angle) * Math.min(height * .25, radius * 1.7), radius: 3.5 + Math.min(9, (concept.mention_count || 1) * .8), color: anchor.color, labelVisible: labelIds.has(concept.id) }; });
}
