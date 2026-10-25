"""API 请求/响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    project_id: str | None = None


class JobSubmit(BaseModel):
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)
    priority: str = "batch"
    confirmed: bool = False


class ToolInvoke(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False


class AgentRun(BaseModel):
    goal: str
    max_iters: int = 20
