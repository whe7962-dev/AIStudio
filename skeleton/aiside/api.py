"""REST API：桌面画布 App（Swift/SwiftUI）通过本地 HTTP 与本后端通信。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from .errors import ConfirmationRequired, PermissionDenied, ToolExecutionError
from .loop import AgentLoop, build_llm_client
from .schemas import AgentRun, JobSubmit, ProjectCreate, ToolInvoke
from .tools.registry import list_tools

router = APIRouter()


def _ws(request: Request):
    return request.app.state.workspace


@router.get("/health")
def health(request: Request):
    ws = _ws(request)
    return {"status": "ok", "provider": ws.provider.name, "version": "0.1.0"}


@router.get("/tools")
def tools():
    return {"tools": [t.to_dict() for t in list_tools()]}


@router.get("/metrics")
def metrics(request: Request):
    return _ws(request).metrics.snapshot()


@router.post("/projects")
def create_project(request: Request, body: ProjectCreate):
    ctx = _ws(request).create_project(body.project_id)
    return {"project_id": ctx.project.project_id}


@router.get("/projects/{project_id}")
def get_project(request: Request, project_id: str):
    ctx = _ws(request).get_project(project_id)
    return ctx.project.to_dict()


@router.post("/projects/{project_id}/jobs")
def submit_job(request: Request, project_id: str, body: JobSubmit):
    ws = _ws(request)
    decision = ws.check_permission(project_id, body.tool, body.params)
    if decision.action == "deny":
        raise HTTPException(status_code=403, detail=decision.reason)
    result = ws.submit(project_id, body.tool, body.params,
                       priority=body.priority, confirmed=body.confirmed)
    return result


@router.post("/projects/{project_id}/tools/{tool_name}")
def invoke_tool(request: Request, project_id: str, tool_name: str, body: ToolInvoke):
    """同步调用工具（读操作 / 快速交互）。ask 时返回 409 提示确认。"""
    ws = _ws(request)
    ctx = ws.get_project(project_id)
    try:
        return ws.dispatcher.dispatch(tool_name, body.params, ctx, body.confirmed)
    except ConfirmationRequired as exc:
        raise HTTPException(status_code=409, detail={"action": "ask", "reason": exc.reason})
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ToolExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/projects/{project_id}/jobs/{job_id}")
def job_status(request: Request, project_id: str, job_id: str):
    return _ws(request).job_status(project_id, job_id)


@router.post("/jobs/{job_id}/confirm")
def confirm_job(request: Request, job_id: str):
    ws = _ws(request)
    try:
        return ws.confirm(job_id)
    except PermissionDenied as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/projects/{project_id}/jobs/incomplete")
def incomplete_jobs(request: Request, project_id: str):
    """扫描本项目未完成任务（崩溃后可据此续跑）。"""
    return {"jobs": _ws(request).recover_incomplete(project_id)}


@router.post("/projects/{project_id}/jobs/{job_id}/resume")
def resume_job(request: Request, project_id: str, job_id: str):
    """从 checkpoint 续跑一个未完成任务。"""
    return _ws(request).resume_job(project_id, job_id)


@router.get("/recovery/incomplete")
def all_incomplete(request: Request):
    """启动恢复扫描：列出所有项目的未完成任务。"""
    return {"jobs": _ws(request).scan_incomplete_jobs()}


@router.post("/projects/{project_id}/agent")
def run_agent(request: Request, project_id: str, body: AgentRun):
    """Agent Loop（s01）：需要配置本地 LLM（LLM_BASE_URL + LLM_MODEL）。"""
    ws = _ws(request)
    client = build_llm_client(ws.settings)
    if client is None:
        raise HTTPException(status_code=501,
                            detail="未配置 LLM_BASE_URL / LLM_MODEL，Agent Loop 不可用（正式版接本地 Qwen3）")
    loop = AgentLoop(ws, project_id, client, max_iters=body.max_iters)
    return loop.run(body.goal)


@router.get("/projects/{project_id}/assets/{cid}")
def get_asset(request: Request, project_id: str, cid: str):
    ws = _ws(request)
    ctx = ws.get_project(project_id)
    try:
        data = ctx.assets.get(cid)
    except KeyError:
        raise HTTPException(status_code=404, detail="asset not found")
    return Response(content=data, media_type="application/octet-stream")
