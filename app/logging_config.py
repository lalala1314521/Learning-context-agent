"""全局日志配置：统一格式、级别与 handler。"""

import logging
import sys

_ROOT_NAME = "learning_agent"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """初始化并返回根 logger。入口模块（server / CLI）启动时调用一次。"""
    logger = logging.getLogger(_ROOT_NAME)
    if getattr(logger, "_lca_configured", False):
        return logger
    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    # 避免重复 handler（reload 场景）
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
    logger.addHandler(handler)
    logger.propagate = False
    logger._lca_configured = True  # type: ignore[attr-defined]
    return logger


def get_logger(name: str) -> logging.Logger:
    """模块级 logger，例如 get_logger(__name__)。"""
    return logging.getLogger(f"{_ROOT_NAME}.{name}")
