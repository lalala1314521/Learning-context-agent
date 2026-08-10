"""配置管理：从 .env 读取环境变量，提供全局配置访问。"""

import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Config:
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

    DEEPSEEK_CHAT_MODEL: str = "deepseek-chat"
    DEEPSEEK_REASONER_MODEL: str = "deepseek-reasoner"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

    DATABASE_PATH: str = str(PROJECT_ROOT / "data" / "learning_agent.db")

    MAX_CONTENT_LENGTH: int = int(os.getenv("MAX_CONTENT_LENGTH", "80000"))
    # ReAct 代理相关
    REACT_MAX_ITERATIONS: int = int(os.getenv("REACT_MAX_ITERATIONS", "8"))
    LLM_MAX_CONCURRENCY: int = int(os.getenv("LLM_MAX_CONCURRENCY", "4"))
    CONVERSATION_TRIM_THRESHOLD: int = int(
        os.getenv("CONVERSATION_TRIM_THRESHOLD", "20")
    )
    SINGLE_LLM_CHUNK_LIMIT: int = int(os.getenv("SINGLE_LLM_CHUNK_LIMIT", "20000"))
    LONG_TEXT_THRESHOLD: int = int(os.getenv("LONG_TEXT_THRESHOLD", "30000"))
    BOOK_TEXT_THRESHOLD: int = int(os.getenv("BOOK_TEXT_THRESHOLD", "150000"))
    CHUNK_OVERLAP_RATIO: float = float(os.getenv("CHUNK_OVERLAP_RATIO", "0.1"))
    TAVILY_MAX_RESULTS: int = 5

    SEMANTIC_ALIGN_ENABLED: bool = _as_bool(
        os.getenv("SEMANTIC_ALIGN_ENABLED"), True
    )
    CONCEPT_LLM_DISAMBIGUATION: bool = _as_bool(
        os.getenv("CONCEPT_LLM_DISAMBIGUATION"), True
    )
    EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "auto")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "bge-small-zh-v1.5")
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "256"))
    CONCEPT_LINK_MIN_CONFIDENCE: float = float(
        os.getenv("CONCEPT_LINK_MIN_CONFIDENCE", "0.6")
    )
    MAX_CONCEPT_LINKS_PER_GRAPH: int = int(
        os.getenv("MAX_CONCEPT_LINKS_PER_GRAPH", "20")
    )

    @classmethod
    def validate(cls) -> None:
        if not cls.DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY not set in .env")
        if not cls.TAVILY_API_KEY:
            raise ValueError("TAVILY_API_KEY not set in .env")


config = Config()
