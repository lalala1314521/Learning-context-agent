# 学习脉络智能体 — 代码全面审查与功能改进方案

> 版本: v1.0  |  日期: 2026-08-09
> 范围: 全部代码审查（后端 26 个 .py、前端 13 个 .js、2 份测试、3 份设计文档）
> 说明: 视觉/UI 设计不在本次范围内（用户已另行完成）

---

## 一、现状总览：已实现功能盘点

### 1.1 架构全貌

```
┌─ 表现层 ──────────────────────────────────────────────┐
│  CLI (app/main.py)         WebUI (app/web/ FastAPI)   │
└──────────────┬──────────────────────────┬──────────────┘
               ▼                          ▼
┌─ LangGraph 编排层 (app/graph/) ───────────────────────┐
│  router → parse_content → [web_search] → generate →    │
│  save_graph → summarize_memory → END                   │
│  manage_graph / list / search / get_graph / chat       │
└──────────────┬─────────────────────────────────────────┘
               ▼
┌─ 工具层 (app/tools/) ─────────────────────────────────┐
│  doc_parser / web_fetcher / web_search /               │
│  knowledge_graph（LangChain @tool 包装 repository）    │
└──────────────┬─────────────────────────────────────────┘
               ▼
┌─ 持久化层 (app/memory/) ──────────────────────────────┐
│  SQLite 业务表：knowledge_graphs / graph_nodes /        │
│  memory_snapshots / graph_links / quiz_questions /      │
│  review_progress                                       │
│  + langgraph-checkpoint-sqlite（对话状态）              │
└────────────────────────────────────────────────────────┘
```

### 1.2 功能矩阵

| 能力 | CLI | WebUI | 状态 |
|---|---|---|---|
| 文本生成脉络（Mermaid + Markdown） | ✔ | ✔ | 稳定 |
| 文件解析 TXT/MD/PDF/DOCX/IPYNB | ✔ | ✔（拖拽上传） | 稳定 |
| URL 抓取（trafilatura/BS4） | ✔ | ✔ | 稳定 |
| 批量文件/URL | ✔ | ✘ | 半成品 |
| Tavily 联网搜索开关 | ✔ | ✔ | 稳定 |
| 输出格式可选 | ✔ | ✔ | 稳定 |
| 脉络列表 / 关键词搜索 / 回顾 | ✔ | ✔ | 稳定 |
| 节点 CRUD + 关联编辑 | ✔ | ✔ | 稳定 |
| 跨脉络链接与跳转 | ✘ | ✔ | WebUI 有 |
| Agent 自动关联已有脉络 | ✘ | ✔（相似度） | 弱 |
| 长期记忆快照 | ✔ | ✔ | 稳定 |
| 出题 / 复习队列 / SM-2 | ✘ | ✔ | 弱（见 2.1） |
| 大纲树 / Mermaid 渲染 / 缩放 / 全屏 | — | ✔ | 稳定 |
| 主题切换 / 拖拽布局 / 导出 | — | ✔ | 稳定 |

### 1.3 代码规模与质量快照

- 后端 26 个模块，职责划分清晰（graph / tools / memory / prompts / web），分层正确。
- 测试 15 个用例，覆盖解析器、CRUD、管理流程、API 冒烟，**均不依赖网络**，设计良好。
- 主要问题集中在：**业务逻辑实现与设计文档落差**、**复习/关联两个核心子系统的算法与完整性缺陷**、**前后端契约不一致**、**异常静默吞掉**、**无日志与可观测性**。

---

## 二、功能完整性评估（缺口与短板清单）

### 2.1 复习出题子系统（用户重点）— 当前"名不副实"

设计文档（WEBUI_V2_UPDATE.md §4）声称"Agent 基于节点与 note 自动出题（名词解释、填空、判断、关联题）"，但实际代码（`api.py:_generate_quiz`）**完全没有调用 LLM**：

```python
quiz_id = repository.add_quiz_question(
    graph_id, node["id"],
    f"什么是「{node['label']}」？",          # ← 模板题
    answer,                                   # ← note 为空时是占位符
    question_type="short_answer",             # ← 永远只有这一种题型
)
```

具体短板：

| # | 问题 | 影响 | 位置 |
|---|---|---|---|
| Q1 | 出题是字符串模板，非 LLM 生成 | 所有题目千篇一律，无判断/填空/关联题，难度恒为 1 | `api.py:110` |
| Q2 | `note` 字段在生成管线里从未被填充 | 设计承诺"label 概括 + note 具体内容"未实现，答案退化为"请回顾：XX" | `nodes.py:187` 只传 label/parent/related |
| Q3 | **SM-2 的 due 计算跨月崩溃**：`now.replace(day=now.day + interval)` | 如 1月31日 +1 天 → `ValueError: day is out of range`，复习直接 500 | `repository.py:445` |
| Q4 | 时间格式混用 | `created_at` 用 SQLite `CURRENT_TIMESTAMP`（UTC、"YYYY-MM-DD HH:MM:SS"），`due_at` 用 `datetime.now().isoformat()`（本地、"YYYY-MM-DDTHH:MM:SS.ffffff"）。**空格(0x20) < 'T'(0x54)，字符串比较结果错误**，到期判断失真 | `repository.py:390/445`、`models.py` |
| Q5 | 忘记（rating=0）后 `repetitions=0, interval=1`，但**没有立即重考机制**，标准 SM-2 应在 10 分钟内重测 | 遗忘曲线修复无效 | `repository.py:430` |
| Q6 | 间隔序列不遵循 SM-2：第 2 次复习固定 3 天而非 `interval × ease`；ease 更新用简化分支而非公式 `EF' = EF + (0.1-(5-q)(0.08+(5-q)*0.02))` | 调度偏离理论模型 | `repository.py:436-444` |
| Q7 | 无"新题每日配额"与到期/新题优先级 | 生成 N 张图后每日队列一次性全量涌入 | `get_due_review` |
| Q8 | 节点 note/label 更新后，旧题目答案不同步 | 知识改了，复习还在考旧内容 | — |
| Q9 | 无掌握度可视化（设计文档列为待办，未做） | 进度面板只有计数 | — |
| Q10 | `get_review_stats` 的 SQL 用字符串拼接 `where + (' AND' if where else 'WHERE')` | 可读性差、易错 | `repository.py:461` |

### 2.2 节点关联子系统（用户重点）— 两套体系割裂、误报率高

| # | 问题 | 影响 | 位置 |
|---|---|---|---|
| L1 | **图内 `related_nodes`（JSON 数组）与图间 `graph_links`（关系表）两套体系并存且无互通**：前端节点面板只渲染 `graph_links`，图内 related 仅显示文本、不可跳转 | 用户在一个图内建立的关联无法用于复习路径 | `repository.py`、`nodePanel.js` |
| L2 | `related_nodes` 是 JSON 字符串，**无外键、无对称性保证、删除节点后留下悬空引用** | 删节点后其他节点仍指向已删 id，界面显示裸 id | `delete_node` |
| L3 | 自动关联 `_char_overlap` 用**字符集合 Jaccard**，中文短标签误报率高（"学习"一词即可撞车 0.5 阈值）；只比 label 不比 note；`relation_type` 恒为 related | 关联质量差、用户需手动删除 | `api.py:64-107` |
| L4 | **前后端契约 bug**：前端 `nodePanel.js:45` 读取 `link.to_node_label / from_node_label`，但后端 `repository.list_links` 返回的是原始行，**根本没有这两个字段**（跨图跳转卡片显示"节点"而非名称） | 跨脉络跳转体验断裂 | `repository.py:306`、`nodePanel.js` |
| L5 | 双向去重只检查 `(from, to_graph, to_node)` 单向；反向后再次触发会重复建链 | 重复链接 | `api.py:78-81` |
| L6 | Mermaid 解析中，**DAG 多父节点被降级为 related**（`parent_map` 已存在父时转 related），丢失方向语义 | 图结构失真 | `mermaid_parser.py:103-108` |
| L7 | `graph_links` 无 `updated_at`、无 label 冗余列、查询需多次 join | 扩展性受限 | `models.py` |

### 2.3 生成管线

| # | 问题 | 影响 | 位置 |
|---|---|---|---|
| G1 | LLM 输出解析全靠正则（`【Mermaid】`/`【Markdown大纲】`），格式稍有偏差即丢内容；**无结构化输出**（JSON mode / `with_structured_output`） | 生成稳定性差 | `nodes.py:136-148` |
| G2 | **Mermaid 无语法校验与重试**（设计文档列为待办，未做） | 前端渲染失败退回原始代码 | `canvasPanel.js:145` |
| G3 | 长文本 `[:12000]` 直接截断，无分块/先摘要策略（设计文档 6.4/9.1 建议未实现） | 长文生成脉络质量下降 | `nodes.py:102` |
| G4 | 搜索模式单一：用内容前 200 字做 query，无"补充/探索"模式细分 | 补充信息相关性差 | `nodes.py:110` |
| G5 | 节点落库异常被 `except Exception: pass` 吞掉 | 用户看到"已保存"但节点全丢，无提示 | `nodes.py:196` |
| G6 | 重复输入相同内容会重复建图，无合并/去重 | 数据膨胀 | — |
| G7 | 每次生成固定 thread_id="web"，checkpoint 状态被反复覆盖，无会话概念 | 无法恢复对话上下文 | `api.py:145` |

### 2.4 数据层与健壮性

| # | 问题 | 影响 |
|---|---|---|
| D1 | 每次操作新建 `sqlite3.connect`，无连接复用/上下文管理器 | 并发写锁竞争、连接开销 |
| D2 | 搜索用 `LIKE '%kw%'` 扫全表，无 FTS5 全文索引 | 数据量增大后检索变慢 |
| D3 | `tags` 存 JSON 字符串，无法高效按标签筛选（设计文档"标签筛选"功能未实现） | — |
| D4 | WebUI 生成接口**同步阻塞**，无超时、无进度、无 SSE（设计文档 9.2 建议未实现） | 大内容生成时浏览器等待数分钟 |
| D5 | `dependencies.get_graph()` 单例无锁，多请求并发 invoke 共享图与 checkpoint；**且 `build_graph()` 未传 checkpointer**——CLI 传了 `SqliteSaver`，Web 端没传，Web 端对话记忆实际不生效 | 潜在状态串扰 + 对话记忆失效 |
| D6 | URL 抓取无 SSRF 防护（可抓内网地址）；上传仅校验后缀、无 MIME/魔数校验 | 安全风险 |
| D7 | Mermaid 渲染 `securityLevel: "loose"` + `innerHTML = svg`，LLM 生成内容直插 DOM | XSS 风险面 |
| D8 | **全项目无 `logging`**（根目录 webui.err.log 存在但代码未写入），错误全靠静默/print | 线上问题不可排查 |
| D9 | LLM 调用无重试/超时/降级封装，Tavily/网络失败直接抛或吞 | 稳定性差 |

### 2.5 前端

| # | 问题 | 影响 |
|---|---|---|
| F1 | 状态散落组件模块变量（currentGraph/currentNodes/current/zoom/view），无统一 store | 组件间同步靠手工，易漏 |
| F2 | 无撤销/重做（设计文档待办未做）、无"全部展开/收起"、无节点拖拽调整层级 | 交互能力缺口 |
| F3 | 删除确认 Modal 用 textarea 显示消息，语义不符 | 交互粗糙 |
| F4 | `modal.js` input 的 value 转义不完整（textarea 用 esc，input 手动 replace 引号） | 潜在 XSS |
| F5 | `nodePanel.renderLinks` 先 remove 再重建 DOM，每次 showNodes 抖动 | 体验 |
| F6 | 历史列表无删除图入口、无标签筛选、无分页 | 数据管理能力弱 |
| F7 | 无会话切换 UI（thread_id 固定） | — |

### 2.6 测试缺口

| 缺口 | 风险 |
|---|---|
| SM-2 调度无单测（跨月边界、interval 序列、rating 分支） | Q3/Q5/Q6 这类 bug 至今未被发现 |
| Mermaid 解析器无复杂语法用例（subgraph、边标签、带引号 label、类定义） | 解析回归 |
| `_auto_link` 无测试 | 误关联回归 |
| 时间比较（due_at）无测试 | Q4 回归 |
| 无 Playwright UI 冒烟（设计文档待办未做） | 前端契约 bug（L4）未被拦截 |

---

## 三、逻辑优化设计（含具体实现方案）

### 3.1 复习出题子系统重构（对应 Q1-Q10）

**目标**：LLM 真出题 + 规范 SM-2 + 数据一致。

**(1) 出题改为 LLM 结构化生成（Q1/Q2）**

新增 Prompt（`prompts/quiz_gen.py`），用 `with_structured_output` 或 JSON mode 强制输出：

```python
class QuizItem(BaseModel):
    question: str
    answer: str
    question_type: Literal["fill", "judge", "short_answer", "relate"]
    difficulty: int  # 1-3
    hint: str = ""

class QuizBatch(BaseModel):
    items: list[QuizItem]
```

调用时机放**生成管线内**（save_graph 之后），而不是 API 层回调里（现在 `_generate_quiz` 在 `api.py` 同步执行，CLI 完全享受不到出题能力）。建议把出题封装为 `graph_service.post_process(graph_id)`，同时被 CLI 与 WebUI 复用。

- 输入：节点 label + note（note 非空时质量才有保障，见 3.3-G2 的 note 生成）
- 对 `relate` 题型，注入该节点的 related_nodes/graph_links 上下文
- **新题每日配额**：`get_due_review` 中 `status='new'` 的题每天最多放 N 张（如 10），其余进入"排队"状态，避免生成大量图后队列爆掉

**(2) 修复 SM-2（Q3/Q5/Q6）**

```python
from datetime import timedelta

def submit_review(review_id: str, rating: int) -> bool:  # rating: 0忘记 / 1模糊 / 2认识
    row = ...  # 读取
    q = rating  # 0,1,2
    now = datetime.now()
    if q < 2:                                   # 忘记或模糊 → 重学
        repetitions = 0
        interval = 1
        ease = max(1.3, ease - 0.15)            # 忘记时降 ease
        due = now + timedelta(minutes=10)        # 立即重考（当天内）
        status = "learning"
    else:                                       # 认识
        repetitions += 1
        ease = max(1.3, ease + (0.1 - (5 - 3) * (0.08 + (5 - 3) * 0.02)))  # SM-2 公式，q=3
        if repetitions == 1:
            interval = 1
        elif repetitions == 2:
            interval = 6
        else:
            interval = round(interval * ease)   # 严格 SM-2: I(n) = I(n-1) × EF
        due = now + timedelta(days=interval)
        status = "mastered" if repetitions >= 5 else "review"
    # 写回...
```

关键修复点：
- `timedelta` 替代 `now.replace(day=...)`（消除跨月崩溃）
- 忘记后 10 分钟重考（`minutes=10`）
- ease 更新走标准公式；间隔序列 1 → 6 → 6×EF

**(3) 统一时间基准（Q4）**

所有 `due_at / last_reviewed_at / updated_at` 统一为 **UTC ISO8601**（带时区），`created_at` 也改用 Python 写入而非 `CURRENT_TIMESTAMP`，避免与 `CURRENT_TIMESTAMP` 的 UTC 无时区格式混比。提供一个 `memory/database.py` 的 `now_utc()` 辅助函数：

```python
def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()
```

SQLite 比较只发生在同一种格式内部，杜绝 Q4。

**(4) 题目与节点同步（Q8）**

`graph_nodes` 增加 `updated_at`（当前没有该列），`list_quiz` 返回时附带 `node_updated_at`，前端或服务端检测 `node_updated_at > quiz_created_at` 时标记"内容已更新，建议重新出题"，提供 `POST /quiz/generate` 按节点重新生成。

**(5) 掌握度统计（Q9）**

`get_review_stats` 增加：各图掌握度 = `mastered / total`，按图分组接口 `GET /review/stats?graph_id=`，前端进度条展示（视觉你已设计，这里只列数据契约）。

### 3.2 节点关联子系统重构（对应 L1-L7）

**(1) 统一关联模型（L1）— 推荐方案**

将 `related_nodes` JSON 逐步迁移为 `graph_links` 关系表（它本身支持同图关联，`from_graph_id == to_graph_id` 即为图内关联），新增 `updated_at` 列；`related_nodes` 保留为**派生缓存/兼容字段**，写入时自动与 `graph_links` 双向同步：

- 写路径：`set_related(node_id, ids)` → 先删该节点同图旧链接 → 批量建 `graph_links` → 重算 `related_nodes`
- 读路径：节点详情统一从 `graph_links` 聚合（图内 + 跨图），`related_nodes` 仅作快照
- **对称性**：建立 A→B 时同时确保 B→A（`ensure_bidirectional`）
- **悬空清理（L2）**：`delete_node` 时事务内 `DELETE FROM graph_links WHERE from_node_id=? OR to_node_id=?`（外键 CASCADE 已覆盖），并 `UPDATE graph_nodes SET related_nodes=...` 移除该 id 的所有引用——写成 `cleanup_node_refs(node_id)` 函数，防止裸 id 残留

**(2) 自动关联升级（L3）**

两阶段：
1. 候选召回：`_char_overlap ≥ 0.45`（保留） + 同 note 关键词命中，控制候选数 ≤ 20
2. 语义确认：对候选批量发给 LLM，输出 `[{from_node, to_node, relation_type: related|cause|contrast|extends, confidence}]`，仅 `confidence ≥ 0.6` 落库，`relation_type` 落 `graph_links.relation_type`

（可选）`relation_type` 注入到 Mermaid 边标签与前端展示。

**(3) 修复契约与去重（L4/L5）**

`repository.list_links` 改为 JOIN 出 label：

```sql
SELECT l.*,
       fn.label AS from_node_label, tn.label AS to_node_label,
       g1.title AS from_graph_title, g2.title AS to_graph_title
FROM graph_links l
LEFT JOIN graph_nodes fn ON fn.id = l.from_node_id
LEFT JOIN graph_nodes tn ON tn.id = l.to_node_id
LEFT JOIN knowledge_graphs g1 ON g1.id = l.from_graph_id
LEFT JOIN knowledge_graphs g2 ON g2.id = l.to_graph_id
WHERE l.from_graph_id = ? OR l.to_graph_id = ?
```

去重：`seen` 同时记录正反向 key `(a,b)` 与 `(b,a)`；建链前检查 `EXISTS` 双向。

**(4) Mermaid 多父语义（L6）**

`_parse_flowchart` 中多父节点不再降级为 related，而是保留 `parent_id` 指向第一个父，同时把**其他父与它的关系**写入 `related_nodes` 并附带方向信息（如 `relation: "parent"`）——需在 `related_nodes` 字段上扩展为 `[{id, relation}]` 对象数组（向后兼容：读时兼容字符串与对象两种形态）。

### 3.3 生成管线优化（对应 G1-G7）

**(1) 结构化输出（G1）**

用 `ChatDeepSeek.with_structured_output(GraphResult)` 定义：

```python
class NodeOut(BaseModel):
    label: str
    note: str                    # ← 新增：节点具体内容（补齐 Q2）
    parent: str = ""             # 引用父节点 label（或 id）
    related: list[str] = []      # 关联节点 label 列表

class GraphResult(BaseModel):
    graph_type: str              # flowchart | mindmap | markdown
    mermaid: str
    markdown: str
    nodes: list[NodeOut]
```

LLM 直出结构化数据后，mermaid 仍作为展示产物由服务端按 nodes 生成（或由 LLM 生成但服务端用结构化数据落库），落库用 `nodes` 字段，**不再依赖正则回退**；`_extract_json_object` 仅作为降级兜底。

**(2) note 落地 + Mermaid 校验重试（G2）**

- `save_graph_node` 落库时带上 `node["note"]`（补全 Q2 的数据基础）
- 新增 `validate_mermaid(code)`：用 `mermaid-js` 服务端解析（Node 子进程）或轻量语法探测（flowchart/mindmap 关键字 + 括号配平）；失败时**带错误信息重试一次**（更新 prompt 追加"上次生成 Mermaid 语法错误：{err}，请修正"），最多 2 次

**(3) 长文本策略（G3）**

超 `MAX_CONTENT_LENGTH` 时：先调用 LLM 做"压缩摘要 + 保留关键点"（`MEMORY_SUMMARY_PROMPT` 复用），再以摘要生成脉络；`raw_content` 仍存全文用于溯源。

**(4) 搜索模式细分（G4）**

`web_search_enabled` 扩展为 `search_mode: off|supplement|explore`：
- supplement：现有行为（以内容摘要为 query）
- explore：以主题词为 query，搜索多条生成"发散脉络"（无用户内容时）

**(5) 会话隔离（G7）**

- WebUI 前端会话切换控件生成 `session_id`（localStorage），`/graphs/generate` 请求携带 `thread_id`
- checkpoint thread_id = 会话 id，消息历史按会话隔离
- 服务端把 `_graph` 单例改为 `{thread_id: graph}` 或直接无状态 invoke（状态放 checkpoint，图可共享，见 D5 修复）

### 3.4 数据层与健壮性（对应 D1-D9）

**(1) 连接管理（D1）**

提供上下文管理器，事务自动 commit/rollback：

```python
from contextlib import contextmanager

@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

Repository 全部方法改用 `with db() as conn:`，同时消除"先 SELECT 再 UPDATE"的竞态窗口（如 `ensure_review` 的插入需加 `UNIQUE(graph_id, node_id, quiz_id)` 约束 + `INSERT OR IGNORE`）。

**(2) FTS5 全文检索（D2）**

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS graphs_fts USING fts5(
    title, description, markdown_outline, raw_content, content='knowledge_graphs', content_rowid='rowid'
);
-- 触发器维护；中文检索需配合 jieba 分词或 trigram tokenizer（sqlite 3.34+ 支持 trigram，可对中文做子串匹配）
```

搜索走 FTS 命中 id 再回表，`ORDER BY bm25()` 排序。

**(3) LLM 调用封装（D9）**

`app/llm/client.py` 统一封装：指数退避重试（2 次）、超时（60s）、异常分类（RateLimit/网络/解析）、token 计数回传日志。

**(4) 日志体系（D8）**

`app/core/logging.py` 配置：`logging.basicConfig` → 文件 `data/app.log` + 控制台；关键节点（生成开始/结束、LLM 耗时/token、异常堆栈）打点。

**(5) 安全（D6/D7）**

- URL 抓取：拒绝内网/保留地址（`ipaddress` 校验解析后的 IP），超时 15s 已有
- 上传：校验扩展名白名单 + 文件头魔数
- Mermaid：`securityLevel: "loose"` 保持（需要 label 渲染），但渲染后 SVG 需经 `DOMPurify` 白名单清洗再入 DOM

**(6) 接口健壮性**

- `PATCH /nodes/{id}` 校验节点存在；`related_nodes` 校验 id 属于同一 graph（防跨图裸 ID）
- 统一错误码结构：`{ok, error: {code, message}}`，前端按 code 提示

### 3.5 生成流程异步化（D4）

`POST /graphs/generate` 改为：
1. 立即返回 `{task_id}`，后台 `BackgroundTasks`/线程池执行生成（独立 thread_id）
2. `GET /tasks/{task_id}` 轮询状态（pending/running/success/error + 进度阶段）
3. 前端生成按钮转 loading + 阶段文案（解析中 → 联网搜索 → 生成中 → 保存中）

（SSE 流式可作为二期，先轮询即可获得明显体验提升）

---

## 四、模块化与扩展性重构建议

### 4.1 目标分层

```
app/
├── core/                       # ★ 新增：领域服务层（现状缺失）
│   ├── services/
│   │   ├── graph_service.py    # 生成流水线：parse→generate→save→quiz→link 编排
│   │   ├── quiz_service.py     # LLM 出题、题目版本同步
│   │   ├── review_service.py   # SM-2 调度、队列、统计
│   │   └── link_service.py     # 关联聚合、对称性、清理、语义关联
│   ├── llm/client.py           # LLM 统一封装（重试/超时/结构化输出）
│   ├── parsers/output.py       # LLM 输出解析（结构化 schema + 正则兜底）
│   └── logging.py
├── graph/                      # 编排层保持薄：只做状态路由，业务逻辑下沉到 services
├── tools/                      # 外部能力适配层（doc/web/search）+ 工具注册表
├── memory/                     # 持久化层：repository + database（统一时间/事务）
├── web/                        # 表现层：API 路由只做参数校验与响应组装
├── cli/                        # ★ 从 main.py 拆分，复用 services，功能与 WebUI 对齐
└── prompts/
```

**重构动线**（小步推进，不重写）：
1. `_auto_link` / `_generate_quiz` 从 `api.py` 迁入 `core/services/`（先搬后改）
2. `nodes.py` 的生成/解析逻辑迁入 `core/parsers/output.py` 与 `core/services/graph_service.py`，`nodes.py` 只剩状态读写
3. CLI 的 `run_cli` 改调 `graph_service`，补上 quiz/review/links 命令，实现双入口功能对齐
4. WebUI API 只做三件事：校验参数（schemas）→ 调 service → 组装响应（ok/error）

### 4.2 前端轻量状态层

用现有 `bus.js` 扩展一个 60 行左右的 `store.js`（不引框架）：

```js
// store.js
const state = { graph: null, nodes: [], view: "mermaid", zoom: 1 };
export const store = {
  get: (k) => state[k],
  set: (patch) => { Object.assign(state, patch); emit("state-changed", { ...state }); },
};
```

组件只依赖 store + bus，删除模块级 `currentGraph/currentNodes/current/zoom/view` 散落变量；`state-changed` 统一驱动渲染，为后续撤销/重做（命令栈）打底。

### 4.3 工具注册表与输入源插件化

`tools/__init__.py` 维护 `INPUT_SOURCES` 注册表（doc/url/text/search），新增输入源（Notion、图片 OCR、剪藏）只需注册新适配器，前端入口由后端 `/api/v1/capabilities` 动态下发（设计文档 8.4 落地）。

### 4.4 配置治理

`config.py` 的类变量 + 测试直接改 `config.DATABASE_PATH` 属全局可变状态。迁移到 `pydantic-settings`，测试用 `monkeypatch.setenv` 或 `dependency_overrides` 注入临时 DB 路径，消除测试间状态污染。

---

## 五、实施优先级与分阶段落地

### 5.1 优先级总表

| 级别 | 项 | 对应问题 | 预估工作量 | 类型 |
|---|---|---|---|---|
| **P0** | SM-2 `timedelta` 修复 + 忘记后 10min 重考 | Q3/Q5 | 0.5 天 | 正确性 Bug |
| **P0** | 统一 UTC 时间写入（`now_utc()`） | Q4 | 0.5 天 | 正确性 Bug |
| **P0** | `/links` 返回 label JOIN 契约修复 | L4 | 0.5 天 | 功能 Bug |
| **P0** | 删除节点清理 related_nodes 悬空引用 + 对称性 | L2 | 1 天 | 数据完整性 |
| **P0** | `repository` 改事务上下文 + `ensure_review` 唯一约束 | D1 | 1 天 | 健壮性 |
| **P1** | LLM 结构化出题（多题型/难度/配额） | Q1/Q7 | 2-3 天 | 核心体验 |
| **P1** | 生成管线填充 note（结构化输出 GraphResult） | Q2/G1 | 2 天 | 核心体验 |
| **P1** | 自动关联两阶段语义化 + relation_type | L3 | 2 天 | 核心体验 |
| **P1** | Mermaid 语法校验 + 重试 | G2 | 1-2 天 | 稳定性 |
| **P1** | 会话隔离（thread_id 前端化 + 图无状态化） | G7/D5 | 1 天 | 架构 |
| **P1** | LLM 调用统一封装（重试/超时/日志） | D9/D8 | 1-2 天 | 可观测性 |
| **P1** | 题目-节点版本同步提示 + 重新出题 | Q8 | 1 天 | 数据一致 |
| **P2** | FTS5 全文检索 | D2 | 1 天 | 性能 |
| **P2** | 掌握度统计图表数据接口 | Q9 | 1 天 | 体验 |
| **P2** | 生成异步化（任务轮询） | D4 | 2-3 天 | 体验 |
| **P2** | 长文本分块摘要 | G3 | 1-2 天 | 质量 |
| **P2** | 前端 store + 撤销/重做 | F1/F2 | 2-3 天 | 交互 |
| **P2** | 标签筛选 + 删除图入口 + 分页 | D3/F6 | 1-2 天 | 数据管理 |
| **P2** | 补测试（SM-2/解析器/auto_link/时间） | 2.6 | 2 天 | 质量 |
| **P2** | CLI 功能对齐（quiz/review/links） | 2.2 | 1 天 | 一致性 |

### 5.2 分阶段落地

**阶段一：止血（第 1 周）— 全部 P0 + P1 的 5/6/11**

- 目标：消灭崩溃类 bug、数据完整性、复习与出题进入"真 LLM"状态
- 验收：跨月复习不再报错；生成后的脉络带 note；题目由 LLM 生成且有多题型；删除节点无悬空关联；日志可查

**阶段二：提质（第 2-3 周）— 剩余 P1 + P2 的 11/12/14**

- 目标：关联语义化、检索提速、长文本可用、掌握度可视化
- 验收：自动关联准确率明显提升；搜索秒回；10 万字文档可生成脉络；复习面板有掌握度进度

**阶段三：扩展（第 4 周起）— 剩余 P2**

- 目标：异步生成、撤销重做、标签体系、双入口对齐
- 验收：大图生成不阻塞 UI；误操作可回退；CLI 与 WebUI 能力一致

### 5.3 建议的落地顺序细节（按依赖排）

1. 先做 3.1(3) 时间统一 → 再修 SM-2（测试先行，补 `test_review_sm2.py`：跨月、interval 序列、rating 分支）
2. 先做 3.4(1) 事务上下文 → 再做节点清理（事务内多写）
3. 先做 LLM 封装 + 结构化输出 → 再做 LLM 出题与 note 生成（依赖同一基建）
4. 前端 store 先行，为撤销/重做与异步轮询提供基座

---

## 六、风险提示

1. **数据结构变更需迁移**：`related_nodes` 从字符串数组扩展为对象数组、`graph_links` 加列，需要 `ALTER TABLE` 兼容脚本（先加列后写新逻辑，读路径兼容旧格式）
2. **LLM 结构化输出在 deepseek-chat 上偶发 schema 不达标**：必须保留正则兜底 + 重试
3. **SQLite 单写者限制**：异步生成并发写可能 `database is locked`，事务 + `busy_timeout`（建议 5000ms）必须配置
4. **FTS5 中文分词**：不引重型分词时用 trigram tokenizer，中文按 3 字窗口匹配，覆盖绝大多数检索场景
5. **不引入 Vue/打包器**（沿用设计文档决策）：前端复杂度通过 store + 组件拆分消化，若后续 UI 复杂度显著上升再评估
