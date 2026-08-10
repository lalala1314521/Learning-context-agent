"""路由共享工具：错误类型与响应包装。"""


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def ok(data):
    return {"ok": True, "data": data, "error": None}
