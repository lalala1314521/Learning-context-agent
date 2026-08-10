"""配置管理：从 .env 读取环境变量，提供全局配置访问。"""

import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

    DEEPSEEK_CHAT_MODEL: str = "deepseek-chat"
    DEEPSEEK_REASONER_MODEL: str = "deepseek-reasoner"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

    DATABASE_PATH: str = str(PROJECT_ROOT / "data" / "learning_agent.db")

    MAX_CONTENT_LENGTH: int = 80000
    TAVILY_MAX_RESULTS: int = 5

    @classmethod
    def validate(cls) -> None:
        if not cls.DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY not set in .env")
        if not cls.TAVILY_API_KEY:
            raise ValueError("TAVILY_API_KEY not set in .env")


config = Config()
