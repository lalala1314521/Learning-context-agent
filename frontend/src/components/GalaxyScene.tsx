import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Application, Container, Graphics, Text, TextStyle } from "pixi.js";
import { motionOrchestrator } from "../motion";
import { api } from "../api";
import { Link, useSearchParams } from "react-router-dom";
import type { Concept, ConceptLink, Domain, GalaxyData } from "../types";

type Point = { id: string; label: string; domainId?: string | null; x: number; y: number; radius: number; color: number; labelVisible: boolean; labelX?: number; labelY?: number };

export function GalaxyScene() {
  const searchRef = useRef<HTMLInputElement>(null);
  const [params] = useSearchParams();
  const [data, setData] = useState<GalaxyData | null>(null);
  const [selected, setSelected] = useState<Concept | null>(null);
  const [selectedRelation, setSelectedRelation] = useState<ConceptLink | null>(null);
  const [query, setQuery] = useState("");
  const [focusId, setFocusId] = useState("");
  const initialZoom = Number(params.get("zoom"));
  const [zoom, setZoom] = useState(() => Number.isFinite(initialZoom) ? Math.min(1.8, Math.max(.65, initialZoom)) : .85);
  const requestedConcept = params.get("concept") || "";
  const requestedFocus = params.get("focus") || "";
  const graphContext = params.get("graph") || "";
  const entrySource = params.get("from") || "";
  const [handoffActive, setHandoffActive] = useState(Boolean(entrySource));
  useEffect(() => { setHandoffActive(Boolean(entrySource)); if (!entrySource) return; const timer = window.setTimeout(() => setHandoffActive(false), 1800); return () => window.clearTimeout(timer); }, [entrySource, requestedConcept]);
  useEffect(() => { api.galaxy().then((payload) => { setData(payload); const target = payload.concepts.find((item) => item.id === requestedConcept || item.canonical_label === requestedConcept); if (target) { setSelected(target); setFocusId(requestedFocus || target.id); if (!Number.isFinite(initialZoom)) setZoom(1.05); motionOrchestrator.emit("concept.focused", target.id); } motionOrchestrator.emit("scene.entered", "galaxy"); }).catch(() => setData({ concepts: [], links: [], domains: [] })); }, [initialZoom, requestedConcept, requestedFocus]);
  useEffect(() => { const onKey = (event: KeyboardEvent) => { if (event.key === "/" && document.activeElement?.tagName !== "INPUT") { event.preventDefault(); searchRef.current?.focus(); } if (event.key === "Escape") { setQuery(""); setFocusId(""); searchRef.current?.blur(); } }; window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, []);
  const compact = useMemo(() => data ? compressGalaxy(data) : null, [data]);
  const displayData = useMemo(() => {
    if (!compact) return null;
    const normalizedQuery = query.trim().toLowerCase();
    const neighborIds = focusId ? new Set([focusId, ...compact.links.flatMap((link) => link.from_concept === focusId ? [link.to_concept] : link.to_concept === focusId ? [link.from_concept] : [])]) : null;
    const concepts = compact.concepts.filter((concept) => {
      const matchesQuery = !normalizedQuery || concept.canonical_label.toLowerCase().includes(normalizedQuery);
      const isInNeighborhood = !neighborIds || neighborIds.has(concept.id);
      return matchesQuery && isInNeighborhood;
    });
    return { ...compact, concepts };
  }, [compact, focusId, query]);
  const selectedRelations = useMemo(() => selected && data && !selected.id.startsWith("domain:") ? data.links.filter((link) => link.from_concept === selected.id || link.to_concept === selected.id).slice(0, 6) : [], [data, selected]);
  const labelFor = useCallback((id: string) => data?.concepts.find((concept) => concept.id === id)?.canonical_label || id, [data]);
  const selectConcept = useCallback((concept: Concept) => { setSelected(concept); setSelectedRelation(null); if (concept.id.startsWith("domain:")) { setZoom(1); setFocusId(""); } motionOrchestrator.emit("concept.focused", concept.id); }, []);
  return <div className="galaxy-layout"><section className="panel galaxy-panel">{handoffActive && <div className="scene-handoff"><span className="scene-handoff-beam" /><div><small>{entrySource === "knowledge" ? "知识脉络接力" : "概念接力"}</small><b>{selected?.canonical_label || requestedConcept || "正在定位概念"}</b></div><em>星图已聚焦</em></div>}<div className="section-heading"><div><span className="eyebrow">GLOBAL KNOWLEDGE SPACE</span><h2>让概念彼此找到</h2></div><div className="galaxy-tools"><span className="status-chip">{zoom < .9 ? "领域总览" : `${data?.concepts.length || 0} 概念`}</span><button className="icon-button" title="缩小镜头" onClick={() => setZoom((value) => Math.max(.65, value - .15))}>−</button><button className="icon-button" title="放大镜头" onClick={() => setZoom((value) => Math.min(1.8, value + .15))}>＋</button><button className="icon-button" title="重置镜头" onClick={() => { setZoom(.85); setFocusId(""); setQuery(""); setSelected(null); setSelectedRelation(null); motionOrchestrator.emit("scene.entered", "galaxy-reset"); }}>◎</button></div></div><div className="galaxy-search"><span>⌕</span><input ref={searchRef} value={query} onChange={(event) => { setQuery(event.target.value); if (event.target.value.trim()) setZoom(1); }} onKeyDown={(event) => { if (event.key === "Enter" && displayData?.concepts[0]) { selectConcept(displayData.concepts[0]); } }} placeholder="搜索概念，定位局部关系（/ 聚焦）" /><small>{query ? `${displayData?.concepts.length || 0} 个匹配` : zoom < .9 ? "领域聚合" : "总览"}</small></div><div className="galaxy-stage">{displayData ? <PixiGalaxy data={displayData} zoom={zoom} focusId={focusId} selectedId={selected?.id} selectedRelationId={selectedRelation?.id} onSelect={selectConcept} /> : <div className="scene-loading">正在铺开领域与关系…</div>}<div className="galaxy-overlay"><span><i className="legend-dot root" />领域光场</span><span><i className="legend-dot" />概念</span><span><i className="legend-line" />真实关系 · 方向箭头</span></div></div></section><aside className="panel galaxy-inspector"><span className="eyebrow">CONCEPT SIGNAL</span>{selected ? <><h3>{selected.canonical_label}</h3><p>{selected.description || (selected.id.startsWith("domain:") ? "缩小视图中的领域聚合。放大镜头可展开其中的概念与真实关系。" : "这个概念还没有摘要。")}</p><div className="signal-card"><small>来自材料</small><strong>{selected.mention_count || 0} 次提及</strong></div><div className="signal-card"><small>掌握状态</small><strong>{selected.mastery?.mastery || "未复习"}</strong></div>{selectedRelations.length > 0 && <div className="relation-list"><small>真实关系 · 点击查看证据</small>{selectedRelations.map((link) => <button key={link.id} className={`relation-card ${selectedRelation?.id === link.id ? "is-selected" : ""}`} onClick={() => { setSelectedRelation(link); motionOrchestrator.emit("relation.selected", link.id); }}><b>{labelFor(link.from_concept)} —{link.relation_type || "related"}→ {labelFor(link.to_concept)}</b><em>{link.status || "pending"}</em></button>)}</div>}{selectedRelation && <div className="evidence-box"><small>关系证据</small><span>{selectedRelation.evidence || "这条关系暂时没有独立证据摘录。"}</span></div>}{!selected.id.startsWith("domain:") && <div className="inspector-actions"><button className="soft-button" onClick={() => setFocusId(selected.id)}>展开邻域 ↗</button>{graphContext && <Link className="soft-button" to={`/knowledge?graph=${encodeURIComponent(graphContext)}&node=${encodeURIComponent(selected.id)}&from=galaxy`}>返回脉络 ↩</Link>}</div>}</> : <div className="empty-state"><span className="empty-glyph">✺</span><p>点击星体，查看概念来源、关系和学习信号。</p></div>}</aside></div>;
}

function compressGalaxy(data: GalaxyData): GalaxyData {
  const topDomains = [...data.domains].sort((a, b) => (b.concept_count || 0) - (a.concept_count || 0)).slice(0, 12);
  const topIds = new Set(topDomains.map((domain) => domain.id));
  const otherConcepts = data.concepts.filter((concept) => concept.domain_id && !topIds.has(concept.domain_id));
  const domains = [...topDomains];
  if (otherConcepts.length) domains.push({ id: "other", name: "其他领域", color: "#7180ad", concept_count: otherConcepts.length });
  return { ...data, domains, concepts: data.concepts.map((concept) => ({ ...concept, domain_id: concept.domain_id && topIds.has(concept.domain_id) ? concept.domain_id : (otherConcepts.length ? "other" : concept.domain_id) })) };
}

function domainOverview(data: GalaxyData): GalaxyData {
  const domainIds = new Set(data.domains.map((domain) => domain.id));
  const concepts = data.domains.map((domain) => ({
    id: `domain:${domain.id}`,
    canonical_label: domain.name,
    description: `${domain.concept_count || 0} 个概念的领域聚合`,
    domain_id: domain.id,
    mention_count: domain.concept_count || 1,
  }));
  const conceptDomain = new Map(data.concepts.map((concept) => [concept.id, concept.domain_id || "other"]));
  const seen = new Set<string>();
  const links: ConceptLink[] = [];
  data.links.forEach((link) => {
    const fromDomain = conceptDomain.get(link.from_concept);
    const toDomain = conceptDomain.get(link.to_concept);
    if (!fromDomain || !toDomain || fromDomain === toDomain || (!domainIds.has(fromDomain) && fromDomain !== "other") || (!domainIds.has(toDomain) && toDomain !== "other") ) return;
    const from = `domain:${fromDomain}`;
    const to = `domain:${toDomain}`;
    const key = `${from}:${to}`;
    if (seen.has(key)) return;
    seen.add(key);
    links.push({ id: `domain-link:${fromDomain}:${toDomain}`, from_concept: from, to_concept: to, relation_type: "domain", status: "confirmed", evidence: "由领域间真实概念关系聚合" });
  });
  return { ...data, concepts, links };
}

type Vec2 = { x: number; y: number };
type Curve = { from: Vec2; c1: Vec2; c2: Vec2; to: Vec2 };
type SelectionAnimation = { curve?: Curve; marker?: Graphics; phase: number };

function PixiGalaxy({ data, zoom, focusId, selectedId, selectedRelationId, onSelect }: { data: GalaxyData; zoom: number; focusId?: string; selectedId?: string; selectedRelationId?: string; onSelect: (concept: Concept) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const targetZoomRef = useRef(zoom);
  const selectedRef = useRef(selectedId);
  const selectedRelationRef = useRef(selectedRelationId);
  const selectionApiRef = useRef<((id?: string, relationId?: string) => void) | null>(null);
  targetZoomRef.current = zoom;
  selectedRef.current = selectedId;
  selectedRelationRef.current = selectedRelationId;
  const overviewMode = zoom < .9 && !focusId;
  useEffect(() => {
    if (!host.current) return;
    let disposed = false;
    const app = new Application();
    const root = host.current;
    app.init({ resizeTo: root, backgroundAlpha: 0, antialias: true, resolution: Math.min(window.devicePixelRatio || 1, 2) }).then(() => {
      if (disposed) return;
      root.appendChild(app.canvas);
      const layoutZoom = overviewMode ? .85 : 1;
      const scene = new Container(); scene.scale.set(layoutZoom); app.stage.addChild(scene);
      const width = root.clientWidth || 700; const height = root.clientHeight || 520;
      const overview = overviewMode;
      const renderData = overview ? domainOverview(data) : data;
      const points = resolveLabelLayout(project(renderData.concepts, renderData.domains, width / layoutZoom, height / layoutZoom), width / layoutZoom, height / layoutZoom);
      const byId = new Map(points.map((point) => [point.id, point]));
      const focusIds = focusId ? new Set([focusId, ...renderData.links.flatMap((link) => link.from_concept === focusId ? [link.to_concept] : link.to_concept === focusId ? [link.from_concept] : [])]) : null;

      // 七层场景：背景、光场、关系、领域、星体、标签、焦点。每层只负责一种语义。
      const backgroundLayer = new Graphics().rect(0, 0, width / layoutZoom, height / layoutZoom).fill({ color: 0x080d1d, alpha: .24 });
      const fieldLayer = new Container();
      const relationLayer = new Container();
      const domainLayer = new Graphics();
      const starLayer = new Container();
      const labelLayer = new Container();
      const focusLayer = new Container();
      scene.addChild(backgroundLayer, fieldLayer, relationLayer, domainLayer, starLayer, labelLayer, focusLayer);

      // 相机与选择态都在现有场景上增量更新，避免每次交互都重建整棵 Pixi 场景。
      app.ticker.add((ticker) => {
        const target = targetZoomRef.current;
        if (motionOrchestrator.isReduced()) {
          scene.scale.set(target);
          return;
        }
        const next = scene.scale.x + (target - scene.scale.x) * Math.min(1, ticker.deltaTime * .12);
        scene.scale.set(next);
      });

      for (let index = 0; index < 12; index += 1) {
        const glow = new Graphics().circle((width / layoutZoom) * ((index * 37) % 100) / 100, (height / layoutZoom) * ((index * 61) % 100) / 100, 22 + (index % 4) * 12).fill({ color: index % 2 ? 0x74e4d2 : 0x6383d9, alpha: .025 });
        fieldLayer.addChild(glow);
      }

      renderData.links.forEach((link) => {
        const from = byId.get(link.from_concept); const to = byId.get(link.to_concept);
        if (!from || !to) return;
        const active = !focusIds || focusIds.has(link.from_concept) || focusIds.has(link.to_concept);
        const curve = curveFor(from, to);
        const relation = new Graphics().moveTo(from.x, from.y).bezierCurveTo(curve.c1.x, curve.c1.y, curve.c2.x, curve.c2.y, to.x, to.y).stroke({ color: 0x6383d9, alpha: active ? .42 : .06, width: active ? 1.7 : 1 });
        relationLayer.addChild(relation);
        const arrowPoint = cubicPoint(curve, .94);
        const tangent = cubicTangent(curve, .94);
        const arrowSize = active ? 5 : 3.5;
        const arrow = new Graphics().moveTo(-arrowSize, -arrowSize * .65).lineTo(0, 0).lineTo(-arrowSize, arrowSize * .65).stroke({ color: 0x87a7ff, alpha: active ? .52 : .1, width: active ? 1.15 : .8 });
        arrow.position.set(arrowPoint.x, arrowPoint.y); arrow.rotation = Math.atan2(tangent.y, tangent.x); relationLayer.addChild(arrow);
      });

      const labelStyle = new TextStyle({ fontFamily: "Microsoft YaHei, sans-serif", fontSize: 12, fill: 0xdbe7ff, fontWeight: "500" });
      const domainStyle = new TextStyle({ fontFamily: "Microsoft YaHei, sans-serif", fontSize: 11, fill: 0x9aa9d5, fontWeight: "700" });
      renderData.domains.forEach((domain) => {
        const domainPoints = points.filter((point) => point.domainId === domain.id); if (!domainPoints.length) return;
        const minX = Math.min(...domainPoints.map((point) => point.x)) - 32; const maxX = Math.max(...domainPoints.map((point) => point.x)) + 32; const minY = Math.min(...domainPoints.map((point) => point.y)) - 32; const maxY = Math.max(...domainPoints.map((point) => point.y)) + 32;
        const color = Number((domain.color || "#596fae").replace("#", "0x"));
        domainLayer.roundRect(minX, minY, maxX - minX, maxY - minY, 26).fill({ color, alpha: .045 }).stroke({ color, alpha: .24, width: 1 });
        const title = new Text({ text: domain.name, style: domainStyle }); title.x = minX + 15; title.y = minY + 12; labelLayer.addChild(title);
      });

      points.forEach((point) => {
        const active = !focusIds || focusIds.has(point.id); const concept = renderData.concepts.find((item) => item.id === point.id); if (!concept) return;
        const star = new Graphics().circle(point.x, point.y, point.radius).fill({ color: point.color, alpha: active ? .94 : .16 });
        star.circle(point.x, point.y, point.radius + 7).stroke({ color: point.color, alpha: active ? .12 : .03, width: 1 });
        star.eventMode = "static"; star.cursor = "pointer"; star.on("pointertap", () => onSelect(concept)); starLayer.addChild(star);
        if (point.labelVisible || focusIds?.has(point.id)) { const label = new Text({ text: point.label, style: labelStyle }); label.alpha = active ? 1 : .2; label.x = point.labelX ?? point.x + point.radius + 7; label.y = point.labelY ?? point.y - 7; labelLayer.addChild(label); }
      });

      let selectionAnimation: SelectionAnimation | undefined;
      const updateSelection = (id?: string, relationId?: string) => {
        const removed = focusLayer.removeChildren();
        removed.forEach((child) => child.destroy());
        selectionAnimation = undefined;
        const selectedPoint = byId.get(id || "");
        if (!selectedPoint) return;
        const pulse = new Graphics().circle(selectedPoint.x, selectedPoint.y, selectedPoint.radius + 14).stroke({ color: 0x74e4d2, alpha: .32, width: 1.5 });
        focusLayer.addChild(pulse);
        const selectedLink = relationId ? renderData.links.find((link) => link.id === relationId) : undefined;
        const from = selectedLink ? byId.get(selectedLink.from_concept) : undefined;
        const to = selectedLink ? byId.get(selectedLink.to_concept) : undefined;
        if (from && to) {
          const curve = curveFor(from, to);
          const edge = new Graphics().moveTo(from.x, from.y).bezierCurveTo(curve.c1.x, curve.c1.y, curve.c2.x, curve.c2.y, to.x, to.y).stroke({ color: 0x74e4d2, alpha: .86, width: 2.5 });
          const marker = new Graphics().circle(from.x, from.y, 4.5).fill({ color: 0x74e4d2, alpha: .9 });
          focusLayer.addChild(edge, marker);
          selectionAnimation = { curve, marker, phase: 0 };
        }
      };
      selectionApiRef.current = updateSelection;
      updateSelection(selectedRef.current, selectedRelationRef.current);
      let phase = 0;
      app.ticker.add((ticker) => {
        const pulse = focusLayer.children[0] as Graphics | undefined;
        if (motionOrchestrator.isReduced()) return;
        phase += ticker.deltaTime * .035;
        if (pulse) {
          pulse.scale.set(1 + Math.sin(phase) * .08);
          pulse.alpha = .22 + (Math.sin(phase) + 1) * .08;
          fieldLayer.alpha = .82 + Math.sin(phase * .4) * .08;
        }
        if (selectionAnimation?.curve && selectionAnimation.marker) {
          selectionAnimation.phase = (selectionAnimation.phase + ticker.deltaTime * .006) % 1;
          const point = cubicPoint(selectionAnimation.curve, selectionAnimation.phase);
          selectionAnimation.marker.position.set(point.x, point.y);
          selectionAnimation.marker.alpha = .45 + Math.sin(selectionAnimation.phase * Math.PI) * .55;
        }
      });
      setReady(true);
    });
    return () => { disposed = true; selectionApiRef.current = null; app.destroy(true, { children: true }); root.replaceChildren(); };
  }, [data, focusId, onSelect, overviewMode]);
  useEffect(() => {
    selectionApiRef.current?.(selectedId, selectedRelationId);
  }, [selectedId, selectedRelationId]);
  return <div ref={host} className={`pixi-host ${ready ? "is-ready" : ""}`} aria-label="全局知识星图" />;
}

function curveFor(from: Point, to: Point): Curve {
  return { from, c1: { x: (from.x + to.x) / 2, y: from.y - 22 }, c2: { x: (from.x + to.x) / 2, y: to.y + 22 }, to };
}

function cubicPoint(curve: Curve, t: number): Vec2 {
  const inverse = 1 - t;
  return { ...curve.from, x: inverse ** 3 * curve.from.x + 3 * inverse ** 2 * t * curve.c1.x + 3 * inverse * t ** 2 * curve.c2.x + t ** 3 * curve.to.x, y: inverse ** 3 * curve.from.y + 3 * inverse ** 2 * t * curve.c1.y + 3 * inverse * t ** 2 * curve.c2.y + t ** 3 * curve.to.y };
}

function cubicTangent(curve: Curve, t: number): Vec2 {
  const inverse = 1 - t;
  return { ...curve.from, x: 3 * inverse ** 2 * (curve.c1.x - curve.from.x) + 6 * inverse * t * (curve.c2.x - curve.c1.x) + 3 * t ** 2 * (curve.to.x - curve.c2.x), y: 3 * inverse ** 2 * (curve.c1.y - curve.from.y) + 6 * inverse * t * (curve.c2.y - curve.c1.y) + 3 * t ** 2 * (curve.to.y - curve.c2.y) };
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

function resolveLabelLayout(points: Point[], width: number, height: number): Point[] {
  const occupied: Array<{ left: number; top: number; right: number; bottom: number }> = [];
  const allowed = new Set<string>();
  const placed = new Map<string, { x: number; y: number }>();
  const candidates = points.filter((point) => point.labelVisible).sort((a, b) => b.radius - a.radius);
  for (const point of candidates) {
    const labelWidth = Math.min(170, Math.max(32, point.label.length * 12));
    const rightSide = point.x + point.radius + 8 + labelWidth <= width - 8;
    const x = rightSide ? point.x + point.radius + 8 : Math.max(8, point.x - point.radius - 8 - labelWidth);
    const y = Math.min(height - 16, Math.max(14, point.y - 7));
    const rect = { left: x - 4, top: y - 3, right: x + labelWidth, bottom: y + 15 };
    if (occupied.some((item) => item.left < rect.right && item.right > rect.left && item.top < rect.bottom && item.bottom > rect.top)) continue;
    occupied.push(rect);
    allowed.add(point.id);
    placed.set(point.id, { x, y });
  }
  return points.map((point) => ({ ...point, labelVisible: allowed.has(point.id), labelX: placed.get(point.id)?.x, labelY: placed.get(point.id)?.y }));
}
