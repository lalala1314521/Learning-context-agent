"""Shared LLM helpers with structured JSON output, retry, concurrency gate and logging."""

import json
import re
import threading
from contextlib import contextmanager

from app.config import config
from app.logging_config import get_logger

logger = get_logger("services.llm")

_llm_semaphore = threading.Semaphore(config.LLM_MAX_CONCURRENCY)


def get_llm(model: str | None = None):
    """统一的 LLM 工厂：所有调用点都应从这里获取模型实例。"""
    from langchain_deepseek import ChatDeepSeek

    return ChatDeepSeek(
        model=model or config.DEEPSEEK_CHAT_MODEL,
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        temperature=0.2,
        max_retries=1,
        timeout=30,
    )


def estimate_tokens(*texts: str) -> int:
    """粗粒度 token 估算：中文约 1.5 字符/token。"""
    total = sum(len(t or "") for t in texts)
    return max(1, round(total / 1.5))


@contextmanager
def llm_concurrency():
    """并发闸门：限制同一时刻的 LLM 调用数，防止触发限流。"""
    with _llm_semaphore:
        yield


def invoke_safe(llm, messages, *, context: str = ""):
    """在并发闸门内调用 LLM 并打日志。返回 AIMessage 对象。"""
    prompt_text = " ".join(
        getattr(m, "content", "") or ""
        for m in (messages if isinstance(messages, (list, tuple)) else [messages])
    )
    logger.info("llm.invoke context=%s ~%dtok", context or "-", estimate_tokens(prompt_text))
    with llm_concurrency():
        return llm.invoke(messages)


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
            response = invoke_safe(current, [HumanMessage(content=prompt)], context="structured")
            text = response.content if hasattr(response, "content") else str(response)
            data = _extract_json_object(text)
            if data is not None:
                return data
        except Exception as exc:
            logger.warning("invoke_structured failed (attempt %d): %s", _, exc)
            continue
    return None
