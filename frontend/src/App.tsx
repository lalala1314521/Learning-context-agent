import { AnimatePresence, motion } from "motion/react";
import { lazy, Suspense, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api } from "./api";
import { motionOrchestrator } from "./motion";
import type { AskResult, Graph, PageKey } from "./types";

const GalaxyScene = lazy(() => import("./components/GalaxyScene").then((module) => ({ default: module.GalaxyScene })));
const KnowledgeScene = lazy(() => import("./components/KnowledgeScene").then((module) => ({ default: module.KnowledgeScene })));

const nav: Array<{ key: PageKey; label: string; glyph: string; path: string }> = [
  { key: "home", label: "工作台", glyph: "⌂", path: "/" },
  { key: "materials", label: "材料与生成", glyph: "✦", path: "/materials" },
  { key: "knowledge", label: "知识脉络", glyph: "◌", path: "/knowledge" },
  { key: "galaxy", label: "知识星图", glyph: "✺", path: "/galaxy" },
  { key: "ask", label: "知识问答", glyph: "↗", path: "/ask" },
  { key: "review", label: "理解练习", glyph: "↻", path: "/review" },
];

type TraceEvent = { text?: string; type?: string; detail?: string; ms?: number };
type JobSnapshot = Awaited<ReturnType<typeof api.job>>;

function useGraphs() {
  const [graphs, setGraphs] = useState<Graph[]>([]);
  useEffect(() => { api.graphs().then(setGraphs).catch(() => setGraphs([])); }, []);
  return graphs;
}

async function waitForJob(id: string, onUpdate: (job: JobSnapshot) => void, maxMs: number, intervalMs = 350) {
  const deadline = Date.now() + maxMs;
  let job = await api.job(id);
  while (job.status === "running" || job.status === "pending") {
    onUpdate(job);
    if (Date.now() > deadline) {
      await api.cancelJob(id).catch(() => undefined);
      throw new Error("任务超过等待时间，已请求取消；可以稍后重试。");
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    job = await api.job(id);
  }
  onUpdate(job);
  return job;
}

export function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const graphs = useGraphs();
  const [theme, setTheme] = useState(() => localStorage.getItem("lca-theme") || "dark");
  const [motionMode, setMotionMode] = useState<"full" | "light" | "static">("full");
  const active = nav.find((item) => item.path === location.pathname)?.key || "home";

  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("lca-theme", theme); }, [theme]);
  useEffect(() => { motionOrchestrator.setMode(motionMode); }, [motionMode]);
  useEffect(() => { motionOrchestrator.emit("scene.entered", location.pathname); }, [location.pathname]);

  return <div className="app-shell">
    <div className="ambient-orbit orbit-one" /><div className="ambient-orbit orbit-two" />
    <aside className="rail">
      <Link to="/" className="brand-lockup" aria-label="返回工作台"><span className="brand-mark">L</span><span><b>脉络</b><small>KNOWLEDGE IN MOTION</small></span></Link>
      <nav className="primary-nav">{nav.map((item) => <Link className={`nav-link ${active === item.key ? "is-active" : ""}`} to={item.path} key={item.key}><span>{item.glyph}</span><label>{item.label}</label>{active === item.key && <motion.i layoutId="nav-rail" />}</Link>)}</nav>
      <div className="rail-footer"><button className="icon-button" title="切换主题" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? "☼" : "☾"}</button><label className="motion-select"><small>动效</small><select value={motionMode} onChange={(event) => setMotionMode(event.target.value as typeof motionMode)}><option value="full">完整</option><option value="light">轻量</option><option value="static">静态</option></select></label></div>
    </aside>
    <main className="main-stage"><header className="top-line"><div><span className="eyebrow">PERSONAL KNOWLEDGE SPACE</span><h1>{nav.find((item) => item.key === active)?.label}</h1></div><div className="top-actions"><span className="live-dot" /> <span className="muted">知识网络持续更新</span><button className="soft-button" onClick={() => navigate("/materials")}>+ 新材料</button></div></header>
      <AnimatePresence mode="wait"><motion.div key={location.pathname} className="route-view" initial={motionOrchestrator.isReduced() ? false : { opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={motionOrchestrator.isReduced() ? undefined : { opacity: 0, y: -8 }} transition={{ duration: motionOrchestrator.isReduced() ? 0 : .35, ease: [0.22, 1, .36, 1] }}><Suspense fallback={<div className="panel empty-large"><span className="eyebrow">SCENE LOADING</span><h2>正在准备知识空间…</h2></div>}><Routes><Route path="/" element={<Dashboard graphs={graphs} />} /><Route path="/materials" element={<Materials />} /><Route path="/knowledge" element={<KnowledgeScene graphs={graphs} />} /><Route path="/galaxy" element={<GalaxyScene />} /><Route path="/ask" element={<Ask />} /><Route path="/review" element={<Review />} /><Route path="*" element={<Navigate to="/" replace />} /></Routes></Suspense></motion.div></AnimatePresence>
    </main>
  </div>;
}

function Dashboard({ graphs }: { graphs: Graph[] }) {
  const navigate = useNavigate();
  return <div className="dashboard-grid"><motion.section className="hero-panel panel" initial={{ opacity: 0, scale: .98 }} animate={{ opacity: 1, scale: 1 }}><span className="eyebrow">TODAY'S THREAD</span><h2>把今天的学习，<em>接入已有的知识。</em></h2><p>材料先被拆成重点、证据和关系，再进入同一个可探索的空间。</p><div className="hero-actions"><button className="primary-button" onClick={() => navigate("/materials")}>生成新脉络 <span>↗</span></button><button className="text-button" onClick={() => navigate("/galaxy")}>探索星图 →</button></div><div className="hero-wave" aria-hidden="true"><svg viewBox="0 0 600 130" preserveAspectRatio="none"><path d="M0 92 C90 24 142 112 238 63 S394 10 600 74" /><path d="M0 111 C120 48 172 133 278 81 S420 32 600 96" /></svg></div></motion.section><section className="metric-panel panel"><span className="eyebrow">NETWORK PULSE</span><strong>{graphs.length || 0}</strong><p>份材料已进入知识空间</p><div className="metric-streak"><i style={{ width: `${Math.min(100, graphs.length * 12)}%` }} /><span>本周连接活跃度</span></div></section><section className="recent-panel panel"><div className="section-heading"><div><span className="eyebrow">RECENT THREADS</span><h3>最近的脉络</h3></div><Link to="/knowledge">查看全部 →</Link></div>{graphs.slice(0, 4).map((graph) => <Link to={`/knowledge?graph=${graph.id}`} className="thread-row" key={graph.id}><span className="thread-orbit" /><span><b>{graph.title || "未命名材料"}</b><small>{graph.source_name || "知识脉络"}</small></span><span className="row-arrow">↗</span></Link>)}{graphs.length === 0 && <EmptyState text="还没有材料，先生成第一条脉络" />}</section><section className="principle-panel panel"><span className="eyebrow">DESIGN PRINCIPLE</span><blockquote>“图不是终点，理解发生在关系被看见的那一刻。”</blockquote><div className="principle-lines"><span /> <span /> <span /></div></section></div>;
}

function Materials() {
  const [content, setContent] = useState(""); const [sourceUrl, setSourceUrl] = useState(""); const [sourceName, setSourceName] = useState("");
  const [goal, setGoal] = useState("理解主线"); const [depth, setDepth] = useState("standard"); const [webSearch, setWebSearch] = useState(false);
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState(""); const [trace, setTrace] = useState<TraceEvent[]>([]); const [jobId, setJobId] = useState(""); const [retryId, setRetryId] = useState("");
  const navigate = useNavigate();

  async function loadUrl() {
    if (!sourceUrl.trim()) return setMessage("先输入一个公开网页地址。");
    setBusy(true); setMessage("正在读取网页正文并估算章节…");
    try { const parsed = await api.parseSource({ url: sourceUrl.trim() }); setContent(parsed.content); setSourceName(parsed.source_name || sourceUrl.trim()); setMessage(`已读取 ${parsed.preview?.characters || parsed.content.length} 字，可继续调整目标后生成。`); }
    catch (error) { setMessage(error instanceof Error ? error.message : "网页读取失败"); } finally { setBusy(false); }
  }

  async function loadFile(file?: File) {
    if (!file) return;
    setBusy(true); setMessage(`正在解析 ${file.name}…`);
    try { const parsed = await api.parseSource({ file }); setContent(parsed.content); setSourceName(parsed.source_name || file.name); setMessage(`已解析 ${file.name}，共 ${parsed.preview?.characters || parsed.content.length} 字。`); }
    catch (error) { setMessage(error instanceof Error ? error.message : "文件解析失败"); } finally { setBusy(false); }
  }

  async function finishGeneration(id: string) {
    setJobId(id); setRetryId("");
    const job = await waitForJob(id, (next) => { setTrace((next.trace || []) as TraceEvent[]); setMessage(next.stage || "正在形成结构…"); }, 300000);
    if (job.status !== "done" || !job.result?.id) throw new Error(job.error || "生成任务没有返回有效脉络");
    motionOrchestrator.emit("knowledge.ready", job.result.id); setMessage("结构已保存，正在打开知识脉络。"); navigate(`/knowledge?graph=${job.result.id}`);
  }

  async function generate() {
    if (!content.trim()) return setMessage("先粘贴或导入一段材料，生成才有依据。");
    setBusy(true); setTrace([]); setRetryId(""); setMessage("正在解析重点、关系和来源…"); motionOrchestrator.emit("material.parsed");
    let activeId = "";
    try { const started = await api.generateAsync(content, { webSearchEnabled: webSearch, learningGoal: goal, generationDepth: depth }); activeId = started.id; await finishGeneration(started.id); }
    catch (error) { if (activeId) setRetryId(activeId); setMessage(error instanceof Error ? error.message : "生成失败"); } finally { setBusy(false); }
  }

  async function retry() { if (!retryId) return; setBusy(true); setMessage("正在重试上一次生成任务…"); try { const started = await api.retryJob(retryId); await finishGeneration(started.id); } catch (error) { setMessage(error instanceof Error ? error.message : "重试失败"); } finally { setBusy(false); } }
  async function cancel() { if (!jobId) return; await api.cancelJob(jobId).catch(() => undefined); setMessage("正在取消任务，已保留当前材料。"); }

  return <div className="materials-layout"><section className="panel material-editor"><div className="section-heading"><div><span className="eyebrow">MATERIAL → STRUCTURE</span><h2>让材料长出关系</h2></div><span className="status-chip">● {sourceName || "本地优先"}</span></div><p className="lede">先说明你想理解什么，再从文本、文件或网页导入材料。系统会找出主线，并把关系绑定到证据。</p><div className="source-controls"><label className="file-drop">选择文件<input type="file" accept=".txt,.md,.pdf,.docx,.ipynb,.py,.html,.json" onChange={(event) => loadFile(event.target.files?.[0])} /></label><input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="或粘贴公开网页地址" /><button className="soft-button" onClick={loadUrl} disabled={busy}>读取网页</button></div><textarea value={content} onChange={(event) => setContent(event.target.value)} placeholder="粘贴一段学习材料…\n\n例如：解释监督学习、损失函数和泛化之间的关系。" /><div className="generation-options"><label>学习目标<select value={goal} onChange={(event) => setGoal(event.target.value)}><option>理解主线</option><option>分析原理</option><option>比较方案</option><option>掌握流程</option><option>准备复习</option></select></label><label>展开深度<select value={depth} onChange={(event) => setDepth(event.target.value)}><option value="overview">概览</option><option value="standard">标准</option><option value="deep">深入</option></select></label><label className="check-option"><input type="checkbox" checked={webSearch} onChange={(event) => setWebSearch(event.target.checked)} />允许联网补充</label></div><div className="editor-footer"><span>{content.length.toLocaleString()} 字符</span><div className="task-actions">{busy && <button className="soft-button" onClick={cancel}>取消任务</button>}{retryId && !busy && <button className="soft-button" onClick={retry}>重试生成</button>}<button className="primary-button" disabled={busy} onClick={generate}>{busy ? "生成中…" : "生成知识脉络 ↗"}</button></div></div>{message && <p className="feedback-line">{message}</p>}</section><section className="panel process-panel"><span className="eyebrow">FORMATION</span><h3>生成过程可见</h3><div className="process-list"><ProcessStep index="01" title="提取主问题" detail="先判断材料要回答什么" active={busy} /><ProcessStep index="02" title="建立证据关系" detail="关系必须能回到原文" active={busy} /><ProcessStep index="03" title="接入知识空间" detail="概念与已有星图对齐" active={false} /></div>{trace.length > 0 && <div className="trace-stream">{trace.slice(-6).map((event, index) => <div className="trace-event" key={`${event.text}-${index}`}><i>{event.type === "tool" ? "◈" : "·"}</i><span>{event.text || "处理中"}</span><small>{event.ms ? `${event.ms}ms` : ""}</small></div>)}</div>}<div className="mini-network"><svg viewBox="0 0 320 160"><path d="M28 115 C90 30 130 144 184 72 S250 40 294 25" /><circle cx="28" cy="115" r="7" /><circle cx="184" cy="72" r="10" /><circle cx="294" cy="25" r="6" /></svg></div></section></div>;
}

function ProcessStep({ index, title, detail, active }: { index: string; title: string; detail: string; active: boolean }) { return <div className={`process-step ${active ? "is-active" : ""}`}><span>{index}</span><div><b>{title}</b><small>{detail}</small></div><i>{active ? "◌" : "·"}</i></div>; }

function Ask() {
  const [question, setQuestion] = useState(""); const [answer, setAnswer] = useState<AskResult | null>(null); const [trace, setTrace] = useState<TraceEvent[]>([]); const [busy, setBusy] = useState(false); const [useDatabase, setUseDatabase] = useState(true); const [jobId, setJobId] = useState(""); const [retryId, setRetryId] = useState(""); const navigate = useNavigate();
  async function finishAsk(id: string, currentQuestion: string) { setJobId(id); setRetryId(""); const job = await waitForJob(id, (next) => setTrace((next.trace || []) as TraceEvent[]), 120000, 300); if (job.status !== "done" || !job.result) throw new Error(job.error || "问答任务没有返回结果"); setAnswer(job.result as unknown as AskResult); motionOrchestrator.emit("concept.focused", currentQuestion); }
  async function submit() { if (!question.trim()) return; setBusy(true); setTrace([]); setAnswer(null); setRetryId(""); let activeId = ""; try { const started = await api.askAsync(question.trim(), useDatabase); activeId = started.id; await finishAsk(started.id, question.trim()); } catch (error) { if (activeId) setRetryId(activeId); setAnswer({ question, answer: error instanceof Error ? error.message : "问答失败", sources: [], has_sources: false }); } finally { setBusy(false); } }
  async function retry() { if (!retryId) return; setBusy(true); try { const started = await api.retryJob(retryId); await finishAsk(started.id, question.trim()); } catch (error) { setAnswer({ question, answer: error instanceof Error ? error.message : "重试失败", sources: [], has_sources: false }); } finally { setBusy(false); } }
  async function cancel() { if (jobId) { await api.cancelJob(jobId).catch(() => undefined); setAnswer({ question, answer: "已请求取消本次检索，可以稍后重试。", sources: [], has_sources: false }); } }
  return <div className="ask-layout"><section className="panel ask-intro"><span className="eyebrow">ASK THE NETWORK</span><h2>问一个问题，<em>沿着证据继续走。</em></h2><p>回答优先来自你的知识库；每个来源都能回到材料和概念。</p><div className="ask-prompt"><textarea value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) submit(); }} placeholder="例如：损失函数为什么会影响泛化？" /><div className="task-actions"><button className="primary-button" onClick={submit} disabled={busy}>{busy ? "检索中…" : "开始探索 ↗"}</button>{busy && <button className="soft-button" onClick={cancel}>取消</button>}{retryId && !busy && <button className="soft-button" onClick={retry}>重试</button>}</div></div><label className="check-option"><input type="checkbox" checked={useDatabase} onChange={(event) => setUseDatabase(event.target.checked)} />使用我的知识库作为主要依据</label><small className="hint">⌘ / Ctrl + Enter 提交</small>{trace.length > 0 && <div className="trace-stream">{trace.slice(-6).map((event, index) => <div className="trace-event" key={`${event.text}-${index}`}><i>{event.type === "tool" ? "◈" : "·"}</i><span>{event.text || "处理中"}</span></div>)}</div>}</section><section className="panel answer-panel">{answer ? <><div className="answer-meta"><span className="status-chip">{answer.has_sources ? "知识库依据" : "需要补充来源"}</span><span>{answer.web_fallback_used ? "含联网补充" : ""}</span></div><h3>{answer.question}</h3><p className="answer-copy">{answer.answer}</p><div className="source-list">{answer.sources.map((source, index) => <button className="source-card" key={`${source.graph_id}-${index}`} onClick={() => source.graph_id && navigate(`/knowledge?graph=${source.graph_id}`)} disabled={!source.graph_id}><span>{String(index + 1).padStart(2, "0")}</span><div><b>{source.title || source.source_name || "知识来源"}</b><small>{source.snippet || "已定位到相关内容"}</small></div><em>{source.graph_id ? "打开脉络 ↗" : "网页来源"}</em></button>)}</div></> : <EmptyState text="回答会在这里展开，并保留来源路径。" />}</section></div>;
}

function Review() {
  const [session, setSession] = useState<{ id: string; mode: string; items: Array<Record<string, unknown>> } | null>(null); const [index, setIndex] = useState(0); const [text, setText] = useState(""); const [feedback, setFeedback] = useState(""); const [busy, setBusy] = useState(false);
  async function start() { setBusy(true); try { const next = await api.reviewSession("feynman"); setSession(next); setIndex(0); setFeedback(""); } catch (error) { setFeedback(error instanceof Error ? error.message : "暂时无法开始练习"); } finally { setBusy(false); } }
  async function submit() { if (!session || !current || !text.trim()) return; setBusy(true); try { const result = await api.answerReview(session.id, { item_id: current.id, text, rating: 2 }); setFeedback(result.feedback); motionOrchestrator.emit("review.persisted", current.id as string); } catch (error) { setFeedback(error instanceof Error ? error.message : "提交失败"); } finally { setBusy(false); } }
  const current = session?.items[index];
  return <div className="review-layout"><section className="panel review-hero"><span className="eyebrow">UNDERSTANDING STUDIO</span><h2>今天不背答案，<em>练习解释。</em></h2><p>题目从你的知识关系中生成，反馈会指出缺失的条件、关系和证据。</p>{current ? <><span className="status-chip">第 {index + 1} / {session?.items.length} 题 · {session?.mode}</span><h3 className="review-question">{String(current.prompt || current.question || "请解释这条知识关系。")}</h3><textarea className="review-answer" value={text} onChange={(event) => setText(event.target.value)} placeholder="先写出你的理解，再补充条件、例子或证据…" /><div className="review-controls"><button className="primary-button" onClick={submit} disabled={busy}>{busy ? "记录中…" : "提交理解 ↗"}</button>{feedback && <span className="feedback-line">{feedback}</span>}</div></> : <button className="primary-button" onClick={start} disabled={busy}>{busy ? "准备中…" : "开始一组理解练习 ↗"}</button>}</section><section className="panel review-map"><span className="eyebrow">LEARNING SIGNAL</span><h3>掌握度应该回到知识空间</h3><div className="signal-ring"><strong>{session ? `${index + 1}` : "—"}</strong><span>{session ? "正在形成理解信号" : "完成练习后显示"}</span></div><p>答题后的概念状态、薄弱关系和下一步复习都会在星图中保留。</p>{feedback && session && index < session.items.length - 1 && <button className="soft-button" onClick={() => { setIndex(index + 1); setText(""); setFeedback(""); }}>下一题 →</button>}</section></div>;
}

function EmptyState({ text }: { text: string }) { return <div className="empty-state"><span className="empty-glyph">·</span><p>{text}</p></div>; }
