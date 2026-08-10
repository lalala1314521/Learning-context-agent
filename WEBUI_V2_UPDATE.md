# 学习脉络智能体 — WebUI 二轮更新方案（v0.2）

> 日期: 2026-08-09  |  状态: 已实现 v0.2  |  前置文档: WEBUI_PLAN.md

## 一、需求总览

| # | 需求 | 类型 |
|---|------|------|
| 1 | 节点展开/收起，并提供更多脉络表示形式 | 功能 |
| 2 | 修复节点“改 / 关联”报错 | 缺陷修复 |
| 3 | Markdown 大纲改为结构化层级视图 | 功能 |
| 4 | 知识回忆题库与复习进度 | 功能 |
| 5 | Agent 自动关联已有脉络 | 功能 |
| 6 | 跨脉络点击跳转 | 功能 |
| 7 | 现代化视觉改版 | 设计 |
| 8 | 面板可拖拽调整 / 展开收起 | 交互 |
| 9 | 画布缩放、平移、全屏 | 功能 |

## 二、逐项设计

### 1. 节点展开 / 收起与脉络表示形式

**交互设计**

- 节点卡片默认折叠：显示 `label`、节点类型、关联数量
- 点击节点展开：显示 `note`（具体内容）、关联节点、所属脉络、操作按钮
- 生成脉络时，Agent 同时输出两层内容：`label` 作为概括，`note` 作为具体解释 / 关键句 / 例子
- 工具栏提供“全部展开 / 全部收起”

**推荐表示形式**

- 概念知识图谱（力导向图）：默认推荐，适合展示概念间关联
- 树状图 / 脑图：层级清晰，适合概念分解
- 时间线：适合历史、过程、发展脉络
- 对比矩阵表：适合概念对比
- 卡片流：适合快速复习浏览
- 流程图：适合步骤、算法
- 保留 Mermaid 与 Markdown 大纲作为导出与备选视图

### 2. 修复节点“改 / 关联”报错

- 已知现象：点击“改”和“关联”报错，删除可用
- 根因推断：当前使用浏览器原生 `prompt / confirm`，部分内置浏览器不支持或返回 null，导致前端直接抛错
- 修复方案：
- 新增通用 `Modal` 组件，替换全部 `prompt / confirm`
  - “改”弹出节点文本与备注编辑框
  - “关联”弹出关联节点 ID 多行输入框，支持现有节点选择
  - “删除”使用 Modal 二次确认
  - 所有操作统一返回 `ok/error`，失败时 toast 展示服务端错误
- 接口现状：`PATCH /api/v1/nodes/{id}` 已支持 `label / related_nodes / order_index`，本轮补齐 `note`

### 3. Markdown 大纲结构化视图

- 后端新增 `GET /api/v1/graphs/{id}/outline`，返回节点树：
  `id / label / note / children / related_nodes / parent_id`
- 前端“大纲”视图按层级渲染为可折叠树：
  - 展开节点显示 note
  - 点击节点同步画布高亮
  - 支持搜索定位
- 保留“原始文本”切换，不再默认展示 raw `<pre>` 内容

### 4. 知识回忆题库与复习进度

**新增数据表**

```sql
CREATE TABLE quiz_questions (
    id            TEXT PRIMARY KEY,
    graph_id      TEXT REFERENCES knowledge_graphs(id) ON DELETE CASCADE,
    node_id       TEXT REFERENCES graph_nodes(id) ON DELETE CASCADE,
    question      TEXT NOT NULL,
    answer        TEXT NOT NULL,
    question_type TEXT DEFAULT 'fill',  -- fill / judge / short_answer / relate
    difficulty    INTEGER DEFAULT 1,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE review_progress (
    id              TEXT PRIMARY KEY,
    graph_id        TEXT REFERENCES knowledge_graphs(id) ON DELETE CASCADE,
    node_id         TEXT REFERENCES graph_nodes(id) ON DELETE CASCADE,
    quiz_id         TEXT REFERENCES quiz_questions(id) ON DELETE CASCADE,
    status          TEXT DEFAULT 'new',   -- new / learning / review / mastered
    repetitions     INTEGER DEFAULT 0,
    interval_days   INTEGER DEFAULT 1,
    ease_factor     REAL DEFAULT 2.5,
    due_at          TIMESTAMP,
    last_reviewed_at TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**功能**

- 生成脉络后，Agent 基于节点与 note 自动出题（名词解释、填空、判断、关联题）
- 复习队列：`GET /api/v1/review` 返回今日到期题目
- 复习反馈三档：认识 / 模糊 / 忘记
- 调度采用 SM-2 简化版：间隔 1 / 3 / 7 / 14 / 30 天，根据反馈调整
- 进度展示：每张脉络的掌握度、已复习次数、待复习数量

### 5. Agent 自动关联已有脉络

- 生成请求新增 `auto_link: bool`，默认开启
- 生成后执行“关联检索”步骤：
  - 用关键词 / LLM 对比新节点与已有脉络的标题、节点、note
  - 命中后创建 `graph_links` 跨脉络链接
  - 同时把目标节点写入新节点的 `related_nodes`，并回写反向关联
- 生成响应新增 `auto_links` 列表：
  `{ from_node_id, from_node_label, to_graph_id, to_graph_title, to_node_id, relation_type }`
- 前端在生成结果中展示“已自动关联 N 个知识”，支持逐条确认或删除
- 提供“手动建立关联”入口

### 6. 跨脉络跳转

**新增数据表**

```sql
CREATE TABLE graph_links (
    id             TEXT PRIMARY KEY,
    from_graph_id  TEXT REFERENCES knowledge_graphs(id) ON DELETE CASCADE,
    from_node_id   TEXT REFERENCES graph_nodes(id) ON DELETE CASCADE,
    to_graph_id    TEXT REFERENCES knowledge_graphs(id) ON DELETE CASCADE,
    to_node_id     TEXT REFERENCES graph_nodes(id) ON DELETE CASCADE,
    relation_type  TEXT DEFAULT 'related',  -- related / cause / contrast / extends
    note           TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

- 节点详情显示“关联到其他脉络”的可点击条目
- 点击后：
  - 当前图压入历史栈
  - 画布打开目标图并高亮目标节点
  - 底部显示面包屑，可逐级返回
- 支持双向跳转与环回

### 7. 现代化视觉改版

- 放弃纸感 / 胶卷纹理，改为“现代知识工作台”风格：
  - 浅色：近白背景、细边框、低饱和蓝绿强调色
  - 深色：炭黑面板、高对比文字
  - 卡片圆角不超过 8px、阴影轻、留白充足
- 字体：系统无衬线为主，标题可适度使用衬线点缀
- 保留双主题、响应式、阅读舒适性要求（栏宽、行高、对比度）

### 8. 布局可拖拽与折叠

- 左栏 / 右栏 / 底部栏支持拖拽分隔条调整宽度或高度，并设置最小尺寸防止挤压
- 每个面板提供折叠按钮，折叠后仅显示图标条
- 布局尺寸保存到 `localStorage`，支持“恢复默认布局”
- 移动端自动单列，不显示拖拽条

### 9. 画布缩放、平移、全屏

- 画布工具栏：放大、缩小、适应画布、100%、全屏
- `Ctrl + 滚轮` 缩放，按住画布拖拽平移
- 缩放范围 20% - 300%，以鼠标位置为缩放中心
- 节点 hover 高亮关联边；点击节点展开详情
- 大图场景可加 minimap（后续迭代）

## 三、数据模型变更汇总

- `graph_nodes.note`：升级为节点“具体内容”，生成时由 Agent 填充
- 新增 `graph_links`：跨脉络链接
- 新增 `quiz_questions`：回忆题库
- 新增 `review_progress`：复习进度与调度

## 四、API 变更（继续使用 /api/v1）

| 方法 | 路径 | 用途 |
|------|------|------|
| `PATCH` | `/api/v1/nodes/{id}` | 增加 `note` 字段更新 |
| `GET` | `/api/v1/graphs/{id}/outline` | 结构化大纲树 |
| `GET` | `/api/v1/links?graph_id=` | 跨脉络链接列表 |
| `POST` | `/api/v1/links` | 手动建立跨脉络链接 |
| `DELETE` | `/api/v1/links/{id}` | 删除链接 |
| `GET` | `/api/v1/quiz?graph_id=` | 题库列表 |
| `POST` | `/api/v1/quiz/{id}/answer` | 提交作答 |
| `GET` | `/api/v1/review` | 今日复习队列与进度 |
| `POST` | `/api/v1/review/{id}` | 提交复习反馈，更新调度 |

生成请求增加 `auto_link: bool`，响应增加 `auto_links`。

## 五、前端组件新增

- `modal.js`：通用弹窗，替换 prompt / confirm
- `nodeDetail.js`：节点展开收起与详情编辑
- `outlineTree.js`：结构化大纲树
- `graphLinks.js`：跨脉络关联列表与跳转
- `zoomCanvas.js`：缩放 / 平移 / 全屏
- `splitLayout.js`：拖拽分隔条与面板折叠
- `quizPanel.js`：出题与作答
- `reviewPanel.js`：复习队列与进度

## 六、实施顺序

### Phase 1：缺陷与基础体验

- 修复“改 / 关联”弹窗问题
- 节点展开收起与 note 编辑
- Markdown 大纲结构化视图
- 现代化视觉改版

### Phase 2：画布与布局

- 画布缩放 / 平移 / 全屏
- 面板拖拽与折叠

### Phase 3：跨脉络

- `graph_links` 数据表与 API
- Agent 自动关联已有脉络
- 跨脉络跳转与面包屑

### Phase 4：复习系统

- 题库生成与作答
- SM-2 复习调度
- 复习进度面板

### Phase 5：测试与打磨

- API 集成测试
- Playwright UI 冒烟
- 性能与错误处理优化

## 七、验收标准

- 内置浏览器中“改 / 关联 / 删除”全部可用
- 节点可展开收起，note 显示具体内容
- 大纲以层级树显示，不再直接展示原始文本
- 大脉络可缩放平移，内容始终可读
- 面板可拖拽调整并记忆布局
- 新脉络可自动关联已有脉络，并支持跨脉络跳转
- 题库可自动生成、作答、记录复习进度

## 八、待确认事项

- 复习算法使用 SM-2 简化版（默认）还是自定义
- 自动关联默认开启（默认展示确认列表）还是手动触发
- 现代化风格的具体偏好：冷灰 / 暖白 / 强调色

## 九、实现记录（2026-08-09）

### 已完成

- [x] 节点展开 / 收起，`note` 具体内容展示与编辑
- [x] 通用 Modal 修复“改 / 关联 / 删除”，不再依赖浏览器 prompt/confirm
- [x] 大纲结构化视图：`GET /api/v1/graphs/{id}/outline` 返回节点树，前端可折叠层级树
- [x] 现代化视觉改版：亮色 / 暗色双主题，卡片、圆角、阴影、对比度均已更新
- [x] 画布缩放（20%-300%）、Ctrl+滚轮、拖拽平移、适应画布、全屏
- [x] 左右栏拖拽分隔条、面板折叠，尺寸记忆到 localStorage
- [x] 自动关联：生成时基于节点文本相似度建立跨脉络 `graph_links`
- [x] 跨脉络跳转：节点面板展示链接，点击跳转目标脉络
- [x] 复习系统：`quiz_questions` 自动出题、`review_progress` SM-2 简化调度、
  今日复习队列与三档反馈

### 仍可迭代

- [ ] 力导向知识图谱 / 时间线 / 对比矩阵等更多表示形式
- [ ] 全部展开 / 全部收起按钮
- [ ] 自动关联逐条确认与删除
- [ ] 节点拖拽调整父子关系、撤销 / 重做
- [ ] 复习统计图表与每图掌握度
- [ ] Playwright UI 冒烟

## 十、v3 实现记录（2026-08-10）

按设计稿 [design/webui-v3-design.html](design/webui-v3-design.html) 与
[FEATURE_DESIGN_GRAPH_REVIEW.md](FEATURE_DESIGN_GRAPH_REVIEW.md) 完成以下升级：

- [x] 青春活力风视觉：橙 / 蓝 / 薄荷 / 阳光黄配色、20px 卡片圆角、渐变背景、
  今日目标胶囊、统计卡、掌握度圆环
- [x] 力导向图谱视图：D3 本地化（`static/vendor/d3.v7.min.js`），节点按类型着色，
  点击节点查看 `note`，支持拖动布局
- [x] Agent 生成节点详情：`label + note + node_type + parent + related` 结构化落库，
  脉络图中可直接展开查看具体内容
- [x] 画布自适应：Mermaid SVG 自动适配画布，保留缩放 / 平移 / 全屏
- [x] 底部面板可拖拽：历史 / 复习 / 记忆区域高度可调并记忆
- [x] 节点类型徽标与掌握度着色：concept / method / case / formula / conclusion
- [x] 复习定位：复习题可一键跳转到对应脉络并高亮节点
- [x] 清理历史乱码数据：删除开发验证产生的乱码记录，标题乱码已修复
- [x] 历史数据迁移：`graph_nodes.node_type` 自动补充列
- [x] 旧图节点自动补全：打开无节点历史图时，从 Mermaid / 大纲解析并落库，
  图谱、大纲、图形视图全部可用（浏览器诊断 37 节点均正常渲染）
- [x] 知识问答：新增 `/api/v1/ask` 与底部问答面板，检索脉络 / 节点 / 记忆后
  回答，区分“已收录知识”与“知识库未覆盖”
- [x] 内容容量：上传上限提升到 50MB，文本解析上限提升到 8 万字符
- [x] 大纲生成提示词优化：节点 8-16 个、层级不超过 3 层、避免碎片化
- [x] 分栏拖拽增强：左右分隔条加宽到 8px，底部面板高度可拖拽并记忆
- [x] 画布放大：Mermaid 自动适配画布并放大字体，图谱节点文字加大

仍待迭代：完整掌握度模型、每日目标 / 连击 / 成就系统、六类题型 LLM 出题引擎、
时间线 / 对比矩阵视图、FSRS 调度。
