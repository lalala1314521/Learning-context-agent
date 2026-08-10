"""Video subtitle ingestion: direct subtitle files and transcript API."""


def fetch_video_subtitles(url: str) -> dict:
    lower = url.lower()
    if lower.endswith((".srt", ".vtt")):
        import httpx
        try:
            response = httpx.get(url, timeout=15, follow_redirects=True)
            response.raise_for_status()
            return {
                "title": url.rsplit("/", 1)[-1],
                "content": _strip_subtitle_timing(response.text),
                "url": url,
            }
        except Exception as exc:
            return {"title": "", "content": "", "url": url, "error": str(exc)}
    if "youtube.com" in lower or "youtu.be" in lower:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            video_id = _extract_youtube_id(url)
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
            content = "\n".join(
                item.get("text", "") for item in transcript
            )
            return {"title": video_id, "content": content, "url": url}
        except ImportError:
            return {
                "title": "",
                "content": "",
                "url": url,
                "error": "需要安装 youtube-transcript-api",
            }
        except Exception as exc:
            return {"title": "", "content": "", "url": url, "error": str(exc)}
    return {
        "title": "",
        "content": "",
        "url": url,
        "error": "暂支持直接字幕文件或 YouTube 链接，B 站请先导出字幕文件",
    }


def _strip_subtitle_timing(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.isdigit():
            continue
        if "-->" in stripped:
            continue
        if stripped.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def _extract_youtube_id(url: str) -> str:
    from urllib.parse import parse_qs, urlparse
    parsed = urlparse(url)
    if "youtu.be" in parsed.netloc:
        return parsed.path.lstrip("/").split("/")[0]
    return parse_qs(parsed.query).get("v", [""])[0]
