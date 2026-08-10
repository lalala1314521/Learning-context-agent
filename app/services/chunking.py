"""Structure-aware chunking and long-text tier estimation."""

import math
import re

from app.config import config

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_CHAPTER_RE = re.compile(
    r"^(第[0-9一二三四五六七八九十百千零〇]+[章节篇部分]"
    r"|Chapter\s+\d+|[A-Za-z0-9]+(?:\.[0-9]+){0,3}\s+\S+)",
    re.IGNORECASE,
)


def classify_content(content: str) -> str:
    length = len(content or "")
    if length <= config.LONG_TEXT_THRESHOLD:
        return "S"
    if length <= config.BOOK_TEXT_THRESHOLD:
        return "M"
    return "L"


def _split_blocks(content: str) -> list[str]:
    """Split into heading-aware blocks with paragraph boundaries preserved."""
    lines = (content or "").splitlines()
    blocks: list[str] = []
    current: list[str] = []
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        is_heading = bool(_HEADING_RE.match(line) or _CHAPTER_RE.match(stripped))
        is_blank = not stripped
        if is_heading and current:
            blocks.append("\n".join(current))
            current = [line]
            continue
        if is_blank and current:
            blocks.append("\n".join(current))
            current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return [b.strip("\n") for b in blocks if b.strip()]


def _split_long_block(block: str, max_chars: int) -> list[str]:
    if len(block) <= max_chars:
        return [block]
    pieces: list[str] = []
    remaining = block
    while remaining:
        cut = min(len(remaining), max_chars)
        break_at = max(
            remaining.rfind("\n", 0, cut),
            remaining.rfind("。", 0, cut),
            remaining.rfind(".", 0, cut),
        )
        if break_at > int(max_chars * 0.5):
            cut = break_at + 1
        pieces.append(remaining[:cut].strip("\n"))
        remaining = remaining[cut:]
    return [piece for piece in pieces if piece]


def chunk_content(
    content: str,
    max_chars: int | None = None,
    overlap_ratio: float | None = None,
) -> list[dict]:
    max_chars = max_chars or config.SINGLE_LLM_CHUNK_LIMIT
    overlap_ratio = overlap_ratio or config.CHUNK_OVERLAP_RATIO
    overlap = min(max_chars - 1, int(max_chars * overlap_ratio))
    blocks = _split_blocks(content)
    chunks: list[dict] = []
    current: list[str] = []
    current_len = 0
    pending_tail = ""
    current_start = None
    cursor = 0

    def flush():
        nonlocal current, current_len, pending_tail, current_start
        if not current:
            return
        text = "\n\n".join(current)
        if pending_tail:
            text = f"{pending_tail}\n\n{text}"
            pending_tail = ""
        chunks.append({
            "chunk_index": len(chunks),
            "text": text,
            "char_start": current_start or 0,
            "char_end": (current_start or 0) + len(text),
        })
        pending_tail = text[-overlap:] if overlap and len(text) > overlap else ""
        current = []
        current_len = 0
        current_start = None

    for block in blocks:
        for piece in _split_long_block(block, max_chars):
            addition = len(piece) + 2 if current else len(piece)
            if current and current_len + addition > max_chars:
                flush()
            if pending_tail and not current:
                current = [pending_tail]
                current_len = len(pending_tail)
                pending_tail = ""
            if current:
                current.append(piece)
            else:
                current.append(piece)
            current_len = sum(len(item) for item in current)
            if len(current) == 1 and current_start is None:
                current_start = cursor
            cursor += len(piece)
    flush()
    return chunks


def detect_chapters(content: str, llm=None) -> list[dict]:
    """Detect top-level chapter boundaries; falls back to structural heuristics."""
    blocks = _split_blocks(content)
    chapters: list[dict] = []
    current_title = "前言"
    current_lines: list[str] = []
    cursor = 0
    for block in blocks:
        first = block.splitlines()[0].strip()
        is_heading = bool(_HEADING_RE.match(block) or _CHAPTER_RE.match(first))
        if is_heading and current_lines:
            chapters.append(_chapter(current_title, current_lines, cursor, content))
            current_title = re.sub(r"^#{1,6}\s+", "", first).strip()
            current_lines = []
        elif is_heading and not current_lines:
            current_title = re.sub(r"^#{1,6}\s+", "", first).strip()
        current_lines.append(block)
        cursor += len(block) + 1
    if current_lines:
        chapters.append(_chapter(current_title, current_lines, cursor, content))
    if len(chapters) <= 1:
        pieces = chunk_content(content, max_chars=max(20000, len(content) // 8))
        chapters = []
        for index, piece in enumerate(pieces):
            chapters.append({
                "title": f"第 {index + 1} 部分",
                "text": piece["text"],
                "char_start": piece["char_start"],
                "char_end": piece["char_end"],
            })
    return chapters


def _chapter(title: str, lines: list[str], cursor: int, content: str) -> dict:
    text = "\n\n".join(lines)
    start = max(0, content.find(text[:80], 0, cursor))
    return {
        "title": title or "未命名章节",
        "text": text,
        "char_start": start,
        "char_end": start + len(text),
    }


def estimate_long_text(content: str) -> dict:
    char_count = len(content or "")
    if char_count <= config.LONG_TEXT_THRESHOLD:
        blocks = 1
    else:
        effective = config.SINGLE_LLM_CHUNK_LIMIT * (1 - config.CHUNK_OVERLAP_RATIO)
        blocks = max(1, math.ceil(char_count / effective))
    estimated_tokens = max(1, round(char_count / 1.5))
    estimated_minutes = round(blocks * 0.27, 1)
    return {
        "char_count": char_count,
        "blocks": blocks,
        "estimated_tokens": estimated_tokens,
        "estimated_minutes": estimated_minutes,
        "tier": classify_content(content),
    }
