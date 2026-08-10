"""Tavily 联网搜索工具。"""

from app.config import config


def search_web(query: str, max_results: int | None = None) -> list[dict]:
    """通过 Tavily 搜索，返回结果列表。"""
    try:
        from tavily import TavilyClient
    except ImportError:
        return [{"title": "错误", "url": "", "content": "tavily-python 未安装"}]

    client = TavilyClient(api_key=config.TAVILY_API_KEY)
    max_r = max_results or config.TAVILY_MAX_RESULTS
    try:
        response = client.search(query, max_results=max_r)
        results = response.get("results", [])
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            for r in results
        ]
    except Exception as e:
        return [{"title": "搜索失败", "url": "", "content": str(e)}]
