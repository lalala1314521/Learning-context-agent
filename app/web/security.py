"""认证占位层。

当前 WebUI 仅在 127.0.0.1 上运行，不启用登录。未来接入账号 / token 时，
只需在此模块补充校验逻辑并在依赖注入处启用，业务路由不需要改动。
"""

from fastapi import Request


def get_current_user(request: Request):
    """未来返回当前用户；当前固定返回 None（匿名本地使用）。"""
    return None
