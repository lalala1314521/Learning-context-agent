"""脉络图生成专用 Prompt。"""

GRAPH_GEN_PROMPT = """请将以下内容整理为一个结构化的知识脉络图。

## 内容
{content}

## 要求
1. 提取核心主题和子主题，建立清晰的层级关系
2. 识别知识点之间的关联（因果 →、对比 ↔、包含 ⊃、递进 →）
3. 根据内容类型选择最合适的图类型：
   - 过程/步骤/算法类 → flowchart LR
   - 层级分类/概念分解 → graph TD
   - 发散性知识点 → mindmap
   - 结构简单层级深 → Markdown 大纲
4. 节点数量控制在 8-16 个，层级不超过 3 层，避免把同一知识点拆成过多碎片
5. 节点标签精简（12字以内），加触发词方便复习；具体解释全部放进节点数据的 note

## 输出格式
请严格按以下四段输出：

【图表类型】: <选择的类型>
【Mermaid】:
```mermaid
...
```
【Markdown大纲】:
# 主题
- 子主题1
  - 细节...
- 子主题2

【关联说明】:
- 概念A → 概念B（因果关系）
- 概念C ↔ 概念D（对比关系）

【节点数据】:
```json
[
  {
    "id": "A",
    "label": "机器学习",
    "note": "让计算机从数据中学习规律并做出预测的学科",
    "node_type": "concept",
    "parent_id": "",
    "related_nodes": []
  }
]
```

节点数据要求：
1. id 必须与 Mermaid 中的节点 id 一致
2. note 写 1-3 句具体解释、关键句或例子，不能为空
3. node_type 只能是 concept / method / case / formula / conclusion
4. parent_id 与 related_nodes 使用本图内的节点 id
5. related_nodes 只保留真正有关联的节点（因果、对比、包含、递进），不要为了关联而关联
"""


MEMORY_SUMMARY_PROMPT = """请阅读下面的知识脉络，生成一段长期记忆摘要，用于跨会话复习检索。

## 脉络内容
{content}

## 输出要求
只输出一个 JSON 对象，不要包含其他文字：
{"summary": "30字以内的主题摘要", "key_points": ["关键知识点1", "关键知识点2", "..."]}
"""
