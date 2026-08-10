"""临时端到端检查：旧图补节点、知识问答、页面结构。"""

import httpx

client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=120)

old = client.get("/api/v1/graphs/e250960b55a4").json()["data"]
print("old graph nodes:", len(old["nodes"]))
outline = client.get("/api/v1/graphs/e250960b55a4/outline").json()["data"]
print("old graph outline roots:", len(outline))

resp = client.post("/api/v1/ask", json={
    "question": "什么是监督学习？知识库里有没有相关内容？",
    "use_database": True,
}).json()
data = resp["data"]
print("ask ok:", resp["ok"], "sources:", len(data["sources"]))
print("answer head:", data["answer"][:80])

page = client.get("/").text
print("ask panel:", "askInput" in page, "| splitter bottom:", "splitter-bottom" in page)
