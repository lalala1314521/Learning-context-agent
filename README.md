# 学习脉络智能体 (Learning Context Agent)

基于 LangGraph + DeepSeek + SQLite 的智能学习助手：把文本、文件或 URL 整理成
Mermaid / Markdown 知识脉络，支持节点级关联、长期记忆与复习检索。

## 快速开始

```bash
uv sync
uv run python -m app.main
```

首次使用前，把 `DEEPSEEK_API_KEY` 和 `TAVILY_API_KEY` 写入项目根目录的 `.env`。

## WebUI

```bash
uv run python -m app.web.server
```

浏览器打开 <http://127.0.0.1:8000>。界面采用青春活力风三栏布局：

- 左栏：文本 / 文件拖拽上传 / URL 抓取 / 联网搜索与输出格式
- 中央：力导向图谱 / Mermaid / 大纲树三视图切换，支持缩放、平移、全屏
- 右栏：掌握度圆环、节点层级与类型徽标、展开查看具体内容、跨脉络跳转
- 底部：脉络历史检索、今日复习队列、知识问答、长期记忆快照
- 顶部：今日目标胶囊、亮色与暗色主题切换

文件上传支持 TXT / MD / PDF / DOCX / IPYNB，单文件不超过 50MB，
单次内容解析上限提升到约 8 万字符；旧图会自动从 Mermaid / 大纲补全节点。
当前 WebUI 仅监听 `127.0.0.1`，暂不启用登录，认证扩展层已预留。

生成脉络时，Agent 会为每个节点补充 `note` 具体内容和 `node_type` 类型，
同时自动创建回忆题并按 SM-2 简化算法安排复习；复习题目可一键定位到对应
脉络节点，节点掌握度会反映在圆环与进度条上。

知识问答面板可检索已有脉络、节点和记忆后回答，并明确区分“已收录知识”与
“知识库未直接覆盖”的内容，方便判断还缺什么。

## v2 全局概念层

`AGENT_DESIGN_V2.md` 引入三层知识模型：文档提及层、全局概念层与领域层。
每次生成脉络后会自动执行概念对齐，重复概念合并为同一个全局实体，并生成
跨文档概念边与「融会贯通报告」。

本地嵌入默认使用确定性 n-gram 向量（无需下载模型）；安装
`sentence-transformers` 与 `sqlite-vec` 后可切换到 BGE + 向量扩展：

```bash
uv sync --extra v2
```

存量数据迁移：

```bash
.venv\Scripts\python.exe scripts\migrate_concepts.py
```

相关 API：`/api/v1/concepts`、`/api/v1/concept-links`、`/api/v1/chunks`。

WebUI 默认首页已切换为全局知识星图：按领域着色、按连接度控制节点大小、
按掌握度显示光晕，支持语义缩放、单击聚焦、双击查看概念详情、框选起点与
终点生成知识链路解说。生成脉络后右上节点面板会展示「本次融会贯通」报告。

星图相关 API：`/api/v1/galaxy`、`/api/v1/domains/refresh`、
`/api/v1/concepts/{start}/path/{end}`。

## 长文本管道

输入超过 3 万字符自动进入 Map-Reduce：结构感知分块、并行抽取、归并对齐，
不再硬截断；超过 15 万字符的整本书会先建立章节母图，再按章生成子图。
原文分块全部进入 `content_chunks`，知识问答升级为「向量检索原文块 + 概念图
双路召回」。

WebUI 通过 `/api/v1/graphs/generate/async` 提交生成任务并用
`/api/v1/jobs/{id}` 轮询进度；解析阶段会先给出字数、分块数、预计耗时与
token 消耗提示。上传已增加魔数校验，URL 抓取会拦截内网地址。

## 多模态复习

复习调度已从 SM-2 简版升级为 FSRS 记忆三变量模型，掌握度统一使用当前
`retrievability`；每次复习写入 `review_history`，星图中的概念详情可查看
记忆曲线。复习中心支持六种模式：闪卡问答、图回忆、连线题、费曼讲述、
苏格拉底追问、跨文档综合，默认开放闪卡与图回忆，其余模式随复习次数解锁。

相关 API：`/api/v1/review/brief`、`/api/v1/review/session`、
`/api/v1/concepts/{id}/curve`。

## 学习伙伴进阶能力

- 学习路径：`GET /api/v1/learning-path?target=...` 从 `depends` / `extends`
  依赖边反向拓扑，标注每个前置概念的掌握状态。
- 知识周报：`GET /api/v1/weekly-report` 汇总本周新增概念、连接、掌握度 Top5
  与下周复习压力。
- Obsidian 导入：`POST /api/v1/sources/import-vault` 批量导入 Markdown vault。
- 视频字幕：`POST /api/v1/sources/video-subtitle` 支持字幕文件 URL 与 YouTube
  转录，`srt/vtt` 也可直接上传。
- Anki 导出：`GET /api/v1/export/anki.apkg`，需要先执行 `uv sync --extra v2`。
- 成就体系：`GET /api/v1/achievements` 提供里程碑解锁状态。

## 常用命令

| 输入 | 说明 |
| --- | --- |
| 任意文本 | 生成并保存知识脉络图 |
| `file:路径` / `files:a;b` | 解析单个 / 批量文件（TXT/MD/PDF/DOCX/IPYNB） |
| `url:网址` / `urls:a;b` | 抓取单个 / 批量网页正文 |
| `list` / `search <关键词>` / `回顾 <主题>` | 列表 / 检索脉络 |
| `open <图ID>` | 查看脉络图与全部节点 |
| `添加节点 <图ID> <文本>` | 手动添加节点 |
| `更新节点 <节点ID> <新文本>` | 修改节点 |
| `删除节点 <节点ID>` | 删除节点 |
| `关联节点 <节点ID> <id1,id2>` | 设置跨节点关联 |
| `/search on\|off` | 联网搜索开关 |
| `/format mermaid\|markdown\|both` | 输出格式 |
| `/quit` | 退出 |

## 目录结构

- `app/graph/`：LangGraph 状态、节点、图组装，以及 Mermaid/Markdown 结构解析
- `app/tools/`：文档解析、网页抓取、Tavily 搜索、脉络图 CRUD
- `app/memory/`：SQLite 业务数据（图谱、节点、记忆快照）与 checkpoint
- `data/learning_agent.db`：运行时生成的数据库
- `tests/`：不依赖网络的冒烟测试

## 测试

```bash
uv run python -m unittest discover -s tests -v
```
