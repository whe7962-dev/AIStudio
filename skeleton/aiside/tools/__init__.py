"""工具集：导入即注册到 TOOLS 注册表。"""

from .registry import TOOLS, Tool, get_tool, list_tools, register

# 导入各工具模块触发 register()
from . import ingest          # noqa: E402,F401
from . import anchor          # noqa: E402,F401
from . import generate        # noqa: E402,F401
from . import score           # noqa: E402,F401
from . import postprocess     # noqa: E402,F401
from . import graph_edit      # noqa: E402,F401
from . import asset_tool      # noqa: E402,F401
from . import model_manager   # noqa: E402,F401

__all__ = ["TOOLS", "Tool", "get_tool", "list_tools", "register"]
