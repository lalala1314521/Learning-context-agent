"""Repository 子模块共享工具。"""

import json


def json_list(value: str | None) -> list:
    """解析数据库中的 JSON 数组字段。"""
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []
