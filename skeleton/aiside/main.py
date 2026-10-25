"""FastAPI 应用入口：一条命令启动本地后端服务。

运行：python -m aiside.main   （或 uvicorn aiside.main:app）
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import router
from .demo import router as demo_router
from .video_demo import router as video_demo_router
from .video_real import router as video_real_router
from .video_workflow import router as video_workflow_router
from .ad_prompts import router as ad_prompts_router
from .logging_config import setup_logging
from .settings import ROOT_DIR, get_settings
from .workspace import Workspace

setup_logging()
logger = logging.getLogger("aiside.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    workspace = Workspace(settings)
    app.state.workspace = workspace
    app.state.settings = settings
    app.state.provider = workspace.provider
    logger.info("workspace ready provider=%s data_dir=%s",
                workspace.provider.name, settings.data_dir)
    if settings.provider == "seedream" and not settings.seedream_enabled:
        logger.warning("AISIDE_PROVIDER=seedream 但缺少 DEMO_API_KEY，请检查 ../demo-api.env")
    yield
    workspace.close()


def create_app() -> FastAPI:
    app = FastAPI(title="端侧AIStudio 后端", version=__version__, lifespan=lifespan)
    app.include_router(router)
    app.include_router(demo_router)
    app.include_router(video_demo_router)
    app.include_router(video_real_router)
    app.include_router(video_workflow_router)
    app.include_router(ad_prompts_router)
    web_dir = ROOT_DIR / "web"
    if web_dir.is_dir():
        # 静态前端挂到根路径；API 路由已在前面注册，优先匹配
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run("aiside.main:app", host=settings.host, port=settings.port, reload=False)
