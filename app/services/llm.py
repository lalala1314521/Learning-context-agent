"""Shared LLM helpers with structured JSON output and retry."""

import json
import re

from app.config import config


def get_llm(model: str | None = None):
    from langchain_deepseek import ChatDeepSeek

    return ChatDeepSeek(
        model=model or config.DEEPSEEK_CHAT_MODEL,
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        temperature=0.2,
        max_retries=1,
        timeout=30,
    )


def _extract_json_object(text: str) -> dict | None:
    text = (text or "").strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    for pattern in (
        r"```(?:json)?\s*\n(\{.*?\})\s*```",
        r"(\{.*\})",
    ):
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            continue
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    return None


def invoke_structured(
    prompt: str,
    llm=None,
    retries: int = 1,
) -> dict | None:
    """Invoke an LLM and coerce the response into a JSON object."""
    from langchain_core.messages import HumanMessage

    current = llm
    for _ in range(max(1, retries)):
        if current is None:
            current = get_llm()
        try:
            response = current.invoke([HumanMessage(content=prompt)])
            text = response.content if hasattr(response, "content") else str(response)
            data = _extract_json_object(text)
            if data is not None:
                return data
        except Exception:
            continue
    return None
