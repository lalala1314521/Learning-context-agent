<!--
  ============================================================================
  学习脉络智能体 (Learning Context Agent) — 实施方案与优化建议
  版本: v1.0  |  日期: 2026-08-09
  ============================================================================
-->

# 学习脉络智能体 — 实施方案与优化建议

## 一、项目目标回顾

构建一个具备记忆能力的智能学习助手，核心能力：

- **输入多样**：接受文本片段、文件上传（PDF/Word/Markdown/TXT）、URL 网页内容
- **输出脉络图**：自动生成知识脉络图（Mermaid 流程图 / 树状图 / 脑图 / Markdown 大纲），无标注时由 Agent 智能选择最佳形式
- **双向编辑**：Agent 可生成内容，用户也可手动增删改脉络节点
- **持久记忆**：短期 & 长期记忆，用 SQLite 持久化（`langgraph-checkpoint-sqlite` 方案你已选定）
- **可选联网**：用户可控制是否启用 Tavily 联网搜索
- **关联检索**：脉络节点之间建立关联关系，方便复习与内容查找


## 二、架构总览

```
+-------------------------------------------------------------+
|                      用户交互层                              |
|    CLI / Jupyter / (未来) WebUI / (未来) API                 |
+-------------------------------------------------------------+
|                     LangGraph Agent                          |
|  +------------+  +------------+  +----------------+         |
|  | 路由节点   |->| 意图识别   |->| 任务执行节点    |         |
|  +------------+  +------------+  +----------------+         |
|       ^                |                |                   |
|       +----------------+----------------+                   |
+-------------------------------------------------------------+
|                    核心工具层 (Tools)                        |
|  +------------+ +------------+ +--------+ +------------+    |
|  | 文档解析   | | 网页抓取   | |Tavily搜索| |脉络图CRUD  |    |
|  +------------+ +------------+ +--------+ +------------+    |
+-------------------------------------------------------------+
|                     持久化层                                 |
|  +---------------------+  +--------------------------+      |
|  | SQLite              |  | langgraph-checkpoint     |      |
|  | (业务数据)           |  | (Agent 对话记忆)          |      |
|  +---------------------+  +--------------------------+      |
+-------------------------------------------------------------+
```

**核心理念**：LangGraph 做流程编排 + 状态管理，DeepSeek 做推理生成，SQLite 做业务数据 + checkpoint 做对话记忆，二者互补。


## 三、推荐目录结构

```
learning-context-agent/
├── app/
│   ├── __init__.py
│   ├── main.py                    # 入口：CLI + 交互循环
│   ├── config.py                  # 配置管理（API Key、模型参数等）
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py               # AgentState 定义 (TypedDict)
│   │   ├── nodes.py               # LangGraph 节点：路由、解析、生成、记忆
│   │   └── builder.py             # 图组装与编译
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── doc_parser.py          # 文件解析工具 (PDF/Word/MD/TXT)
│   │   ├── web_fetcher.py         # URL 内容抓取
│   │   ├── web_search.py          # Tavily 联网搜索
│   │   └── knowledge_graph.py     # 脉络图 CRUD 工具
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── database.py            # SQLite 初始化 + 连接管理
│   │   ├── models.py              # 数据模型定义
│   │   └── repository.py          # DAO / Repository 层
│   └── prompts/
│       ├── __init__.py
│       ├── system.py              # 系统 Prompt 模板
│       └── graph_gen.py           # 脉络图生成专用 Prompt
├── data/
│   └── learning_agent.db          # SQLite 数据库文件（运行时生成）
├── .env                           # 环境变量 (已存在)
├── pyproject.toml                 # 项目配置 (已存在)
└── IMPLEMENTATION_PLAN.md         # 本方案文档
```


## 四、核心设计

### 4.1 LangGraph 状态定义 (`graph/state.py`)

设计一个 `AgentState`，它在 Graph 的节点之间流动：

```python
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]   # 对话历史
    user_input: str               # 当前用户输入
    input_type: str               # "text" | "file" | "url" | "manage" | "search"
    parsed_content: str           # 解析后的原始文本内容
    web_search_enabled: bool      # 是否开启联网搜索
    supplementary_info: str       # 联网搜索补充信息
    current_graph_id: str         # 当前操作的脉络图 ID
    graph_mermaid: str            # 最后一次生成的 Mermaid 代码
    graph_markdown: str           # 最后一次生成的 MD 大纲
    action: str                   # 下一步动作路由
    error: str                    # 错误信息
```

### 4.2 LangGraph 节点设计 (`graph/nodes.py`)

| 节点 | 职责 | 关键逻辑 |
|------|------|----------|
| `router` | 入口路由 | 识别输入类型（text/file/url/manage），决定分发到哪个下游节点 |
| `parse_content` | 内容解析 | 文本直接透传；文件走 `doc_parser` tool；URL 走 `web_fetcher` tool |
| `web_search` | 联网搜索（条件） | 当 `web_search_enabled=True` 时触发，补充上下文 |
| `generate_graph` | 脉络图生成 | 调用 DeepSeek，传入解析内容 + 已有脉络结构，生成 Mermaid + Markdown |
| `manage_graph` | 用户手动管理 | 用户增删改脉络节点，Agent 理解意图后调用 `knowledge_graph.py` tools |
| `summarize_memory` | 记忆总结 | 定期 / 按需对历史对话做摘要，写回长期记忆 |

**流转路径**：
```
router -> parse_content -> [web_search(optional)] -> generate_graph -> END
router -> manage_graph -> END
```

### 4.3 SQLite 数据模型 (`memory/models.py`)

你选择了 `langgraph-checkpoint-sqlite` 来持久化 LangGraph 的对话状态，这是正确的。但**对话记忆**（checkpoint）和**业务数据**（脉络图内容）是两类不同的东西，建议分开存储。`langgraph-checkpoint-sqlite` 负责前者；业务数据由我们自己的 SQLite 表管理。

```sql
-- 脉络图主表
CREATE TABLE knowledge_graphs (
    id              TEXT PRIMARY KEY,          -- UUID
    title           TEXT NOT NULL,             -- 脉络图标题
    description     TEXT,                      -- 简短描述
    graph_type      TEXT DEFAULT 'auto',       -- mermaid_flow / mermaid_tree / mermaid_mindmap / markdown / auto
    mermaid_code    TEXT,                      -- Mermaid 代码块
    markdown_outline TEXT,                     -- Markdown 大纲版本
    raw_content     TEXT,                      -- 原始输入内容（溯源）
    source_type     TEXT,                      -- text / file / url
    source_name     TEXT,                      -- 文件名或 URL
    tags            TEXT,                      -- JSON 数组标签
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 脉络节点表（实现节点级关联，方便复习检索）
CREATE TABLE graph_nodes (
    id              TEXT PRIMARY KEY,
    graph_id        TEXT NOT NULL REFERENCES knowledge_graphs(id),
    parent_id       TEXT REFERENCES graph_nodes(id),   -- 父节点（树/层级结构）
    label           TEXT NOT NULL,                      -- 节点文本
    note            TEXT,                               -- 用户或 Agent 添加的备注
    related_nodes   TEXT,                               -- JSON: ["node_id_1","node_id_2"] 跨节点关联
    order_index     INTEGER DEFAULT 0,
    created_by      TEXT DEFAULT 'agent',               -- 'agent' | 'user'
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 对话记忆摘要表（长期记忆结构化存储）
CREATE TABLE memory_snapshots (
    id              TEXT PRIMARY KEY,
    graph_id        TEXT REFERENCES knowledge_graphs(id),
    summary         TEXT NOT NULL,                      -- 摘要内容
    key_points      TEXT,                               -- JSON: 关键知识点列表
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_graph_nodes_graph ON graph_nodes(graph_id);
CREATE INDEX idx_memory_snapshots_graph ON memory_snapshots(graph_id);
```


### 4.4 数据库连接管理 (`memory/database.py`)

关键点：**让 `langgraph-checkpoint-sqlite` 和我们的业务数据共享同一个 SQLite 连接**。这不是必须的，但可以避免两个数据库文件的维护成本。

```python
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

DATABASE_PATH = "data/learning_agent.db"

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def get_checkpointer() -> SqliteSaver:
    """创建 LangGraph 使用的 checkpoint saver，指向同一个 db 文件"""
    return SqliteSaver.from_conn_string(DATABASE_PATH)
```


### 4.5 Tool 设计

#### 4.5.1 文档解析 (`tools/doc_parser.py`)

```
工具名: parse_document
描述:   解析上传的文件，提取文本内容
输入:   file_path (str)
输出:   title, content (str), file_type
实现:
  - .txt / .md  -> 直接读取
  - .pdf        -> PyPDF2 或 pdfplumber
  - .docx       -> python-docx
  - .ipynb      -> nbformat 解析
```

#### 4.5.2 网页抓取 (`tools/web_fetcher.py`)

```
工具名: fetch_url
描述:   抓取网页正文内容
输入:   url (str)
输出:   title, content (str), url
实现:   httpx + BeautifulSoup / trafilatura（推荐 trafilatura，提取正文效果好）
```

#### 4.5.3 联网搜索 (`tools/web_search.py`)

```
工具名: search_web
描述:   通过 Tavily 执行联网搜索
输入:   query (str), max_results (int = 5)
输出:   results: list[{title, url, content}]
实现:   TavilySearchResults(max_results=n)
```

#### 4.5.4 脉络图 CRUD (`tools/knowledge_graph.py`)  <- 核心

```
工具名: create_graph / search_graph / update_node / add_node / delete_node / get_graph
描述:   对 knowledge_graphs 和 graph_nodes 表做 CRUD
实现:
  - Agent 调用这些 tool 来持久化脉络
  - 用户在 CLI 中也可以通过自然语言触发管理命令
```


### 4.6 Prompt 设计（关键）

脉络图生成是核心能力。建议设计分层 Prompt：

**系统 Prompt（`prompts/system.py`）**：定义 Agent 的人设、工具使用规则、输出规范

**脉络图生成 Prompt（`prompts/graph_gen.py`）**：专门指导 DeepSeek 如何把一段知识内容变成一个结构化的脉络图。核心指令要点：

1. 先提取核心主题和子主题的层级关系
2. 识别知识点之间的关联（因果、对比、包含、递进等）
3. 选择合适的图类型：
   - **流程图 (flowchart)**：过程 / 步骤 / 算法类内容
   - **树状图 (graph TD/LR)**：层级分类、目录结构、概念分解
   - **脑图 (mindmap)**：发散性知识点，中心主题辐射
   - **Markdown 大纲**：结构简单、层级深的纯文字内容
4. 在节点 label 上加简洁的触发词，方便复习时联想
5. 输出两个格式：Mermaid 代码块 + Markdown 大纲


## 五、实施步骤（推荐分阶段推进）

### Phase 1 — 基础跑通（MVP）

- [x] 1. 安装依赖：`langgraph-checkpoint-sqlite langgraph langchain-core langchain-deepseek tavily-python trafilatura python-docx PyPDF2 httpx`
- [x] 2. 搭建 `config.py` 从 `.env` 读配置
- [x] 3. 实现 `memory/database.py` + `memory/models.py`（建表脚本）
- [x] 4. 实现 `tools/doc_parser.py` 和 `tools/web_fetcher.py`
- [x] 5. 实现 `tools/web_search.py`（Tavily）
- [x] 6. 实现 `graph/state.py` + `graph/nodes.py` + `graph/builder.py`（最简流程：输入文本 -> 生成 Mermaid）
- [x] 7. 实现 `tools/knowledge_graph.py`（持久化脉络到 SQLite）
- [x] 8. 实现 `main.py` CLI 交互入口
- [x] 9. 端到端验证：输入一段文字 -> 生成脉络图 -> 保存到数据库 -> 可查询（冒烟测试 + Mock LLM 全流程）

### Phase 2 — 记忆与关联

- [x] 10. 接入 `langgraph-checkpoint-sqlite` 做对话记忆
- [x] 11. 实现 `summarize_memory` 节点（长期记忆摘要）
- [x] 12. 实现节点间的 `related_nodes` 关联逻辑（Mermaid/Markdown 自动解析落库）
- [x] 13. 支持复习查询：「回顾 / 复习 XX 主题」，并支持 `open <图ID>` 查看完整节点

### Phase 3 — 增强与体验

- [x] 14. 支持用户手动增删改脉络节点（`manage_graph` 流程 + 关联节点命令）
- [x] 15. 支持联网搜索开关
- [x] 16. 支持多文件 / 多 URL 批量处理
- [x] 17. 输出格式可选（纯 Mermaid / 纯 Markdown / 两者都输出）
- [ ] 18. （远期）WebUI 或 Jupyter Widget 可视化展示


## 六、对你的方案的优化建议

### 6.1 双数据库策略是正确的，但有细节要处理

你选 `langgraph-checkpoint-sqlite` 很对——它自动管理对话状态序列化/反序列化，比手写 message history 强太多。但要注意：

- **Checkpoint 存的是 LangGraph State 的完整快照**，包含 `messages` 列表、`parsed_content` 等所有字段。如果一段对话很长，checkpoint 数据量会膨胀。
- 建议在 `summarize_memory` 节点中定期把对话总结写入我们自己的 `memory_snapshots` 表，然后把 `messages` 列表裁剪（保留最近 N 轮），再继续。LangGraph 的 `SqliteSaver` 支持这个。
- **不要让 checkpoint 表承担业务查询的职责**。业务查询（「找某个主题的所有脉络」）走我们自己的 `knowledge_graphs` 表。

### 6.2 脉络图「关联性」是精髓，不要只做树

你提到「脉络图要有关联性，方便用户复习与内容查找」——这点非常关键。我建议：

- `graph_nodes.related_nodes` 字段是实现跨节点关联的关键。例如「过拟合」同时关联「正则化」（因果）和「偏差-方差权衡」（对比）。
- 生成脉络时，让 DeepSeek 显式输出关联关系（JSON），Agent 解析后写入。
- 在复习时，可以用 `related_nodes` 做类似「知识图谱」的路径查询——比如「从这个概念出发，有哪些相关概念？」

### 6.3 记忆要做分层，不是一味累加

```
短期记忆 (messages[]) -> 当前对话上下文，LangGraph checkpoint 自动管理
   | 摘要沉淀
长期记忆 (memory_snapshots) -> 结构化关键点，方便跨会话检索
   | 关联
脉络记忆 (knowledge_graphs + graph_nodes) -> 知识点结构化存储，可直接检索
```

三层各司其职，检索效率最高。

### 6.4 联网搜索要收敛，不要发散

你提到「用户控制是否联网搜索」，建议设计得更细：

- **模式 1：关闭** — 只用已上传/已输入的内容生成脉络
- **模式 2：补充** — 在解析内容的基础上，搜索补充细节和背景知识
- **模式 3：探索** — 以一个主题词为起点，搜索扩展成完整脉络（没有用户输入内容时）

### 6.5 DeepSeek 模型选择的考量

从你 `.env` 中配置的 key 来看，建议使用 `deepseek-chat`（V3）作为主力——性价比最高，中文理解优秀。对于特别复杂的脉络生成，可以切换 `deepseek-reasoner`（R1），让它在推理阶段就构建好知识结构。

可以考虑在生成脉络图时使用 `deepseek-reasoner`（推理能力强，适合结构化输出），日常对话用 `deepseek-chat`（响应快，成本低）。

### 6.6 几点「不要做」的建议

- **不要把所有文件内容塞进 checkpoint**。大文件解析后的原始全文应只存业务表，checkpoint 里放的 messages 是 LLM 的上下文，放摘要或关键段落即可。
- **不要一开始就做 WebUI**。CLI 或 Jupyter Notebook 足够验证整个流程，调顺了再考虑前端。你已经有 JupyterLab，可以直接在 Notebook 里做交互式原型。
- **不要过度设计 graph 节点**。LangGraph 的节点应该是「粗粒度」的任务单元，不是每个微操都做一个节点。初始阶段 4-5 个节点足够。


## 七、关键技术决策速查

| 决策点 | 推荐方案 | 备选 |
|--------|---------|------|
| Agent 框架 | LangGraph | LangChain AgentExecutor |
| LLM | DeepSeek-V3 (chat) + R1 (reasoner) | — |
| 对话记忆 | `langgraph-checkpoint-sqlite` | 手写 message history |
| 业务数据 | SQLite（同库不同表） | PostgreSQL / Chroma |
| 联网搜索 | Tavily Search | DuckDuckGo / SerpAPI |
| 文档解析 | trafilatura (HTML) / PyPDF2 (PDF) / python-docx (Word) | Unstructured.io |
| 脉络可视化 | Mermaid (代码) | Graphviz / D3.js |


## 八、依赖清单

```bash
# 核心 Agent 框架
uv add langgraph langgraph-checkpoint-sqlite langchain-core langchain-deepseek

# 工具依赖
uv add tavily-python          # 联网搜索
uv add trafilatura            # 网页正文提取
uv add httpx                  # HTTP 客户端
uv add python-docx            # Word 解析
uv add PyPDF2                 # PDF 解析
uv add beautifulsoup4         # HTML 解析（trafilatura 的备用）
```

> 注：`langchain-deepseek` 你已安装，`pandas` 和 `matplotlib` 你已有，如需做数据可视化可复用。


## 九、风险与注意事项

1. **Token 消耗**：长文本 + 脉络生成 + Mermaid 输出会消耗较多 token，建议对输入做截断（如 8000 字符以内）或分块处理
2. **DeepSeek API 稳定性**：做好重试和降级逻辑
3. **SQLite 并发**：如果未来需要多用户 / 多线程，SQLite 可能成为瓶颈，届时可迁移到 PostgreSQL
4. **Mermaid 语法正确性**：LLM 生成的 Mermaid 有时有语法错误，可以考虑加一个简单的语法校验 + 重试环节
5. **隐私**：用户上传的文件和 URL 内容会发送给 DeepSeek API，需要注意敏感信息处理


## 十、当前进度（2026-08-09）

- Phase 1（MVP）已完成：配置、SQLite、文档/网页/搜索工具、LangGraph 图、CLI 均已跑通。
- Phase 2 已完成：checkpoint 对话记忆、`summarize_memory` 长期记忆、`related_nodes` 节点关联自动落库、复习检索与 `open` 查看。
- Phase 3 已完成前 4 项：节点管理命令、联网开关、批量文件/URL、输出格式选择；WebUI 留作远期。
- 新增 `tests/test_learning_agent.py`（9 个冒烟测试），覆盖解析器、CRUD、管理流程、批量输入、格式过滤和完整图流程，均不依赖网络。
