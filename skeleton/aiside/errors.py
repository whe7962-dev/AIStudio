"""统一错误类型。"""


class AISideError(Exception):
    """骨架通用错误基类。"""


class PermissionDenied(AISideError):
    """越权 / 网络红线 / 未确认的破坏性操作被拒绝。"""


class ConfirmationRequired(AISideError):
    """操作需要用户确认。"""

    def __init__(self, tool_name: str, reason: str = ""):
        super().__init__(reason or f"{tool_name} 需要用户确认")
        self.tool_name = tool_name
        self.reason = reason


class ToolExecutionError(AISideError):
    """工具执行失败（已重试）。"""
