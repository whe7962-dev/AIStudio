"""端侧AIStudio 后端骨架。

正式产品形态：原生 macOS 桌面画布应用（Swift/SwiftUI）作为前端，
本包作为「本地推理与图像处理管线」Python 子进程后端，通过本地 HTTP 接口通信。
骨架阶段以 FastAPI + 本地服务承载后端能力，可独立运行与测试。
"""

__version__ = "0.1.0"
