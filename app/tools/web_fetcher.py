"""网页抓取工具：提取 URL 正文内容。"""


def fetch_url(url: str) -> dict:
    """抓取网页正文，返回 title, content, url。"""
    try:
        import trafilatura
    except ImportError:
        return _fetch_with_bs4(url)

    downloaded = trafilatura.fetch_url(url)
    if downloaded is None:
        return {"title": "", "content": "", "url": url, "error": "无法下载网页内容"}

    result = trafilatura.extract(downloaded, output_format="json", with_metadata=True, url=url)
    if result is None:
        return {"title": "", "content": "", "url": url, "error": "无法提取网页正文"}

    import json
    data = json.loads(result)
    return {
        "title": data.get("title", ""),
        "content": data.get("text", ""),
        "url": url,
    }


def _fetch_with_bs4(url: str) -> dict:
    import httpx
    from bs4 import BeautifulSoup

    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        return {"title": "", "content": "", "url": url, "error": str(e)}

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    title = soup.title.string.strip() if soup.title else ""
    content = soup.get_text(separator="\n", strip=True)
    return {"title": title, "content": content, "url": url}
