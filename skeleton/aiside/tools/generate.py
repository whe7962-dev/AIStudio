"""P4 生成编排：generate_image（草稿/终稿双轨 + 变体 + 种子 + 缓存 + 降级链）。

- 生成节点用 (prompt, seed, model, anchor) 哈希做缓存。
- 失败：自动重试 1 次；仍失败按 OOM 降级链（降分辨率 → 降步数 → 换轻量模型）逐级尝试，
  每级在结果与 job 记录中标 degraded，禁止静默。
- demo 期走豆包 Seedream（网络由 dispatcher 按白名单放行）；正式版切本地 provider。
"""

from __future__ import annotations

from .registry import register, Tool

_TOOL = Tool(
    name="generate_image",
    description="生成候选图（draft / final / inpaint）。demo 期可走豆包 Seedream，正式版本地推理。",
    json_schema={
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["draft", "final", "inpaint"]},
            "anchor_id": {"type": "string"},
            "prompt": {"type": "string"},
            "channel": {"type": "string"},
            "seed": {"type": "integer"},
            "count": {"type": "integer", "default": 4},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "steps": {"type": "integer"},
            "model": {"type": "string"},
            "node_id": {"type": "string"},
            "resume": {"type": "object", "description": "从 checkpoint 续跑：{done, asset_ids}"},
        },
        "required": ["mode", "prompt", "seed"],
    },
    permission="allow",
    network=False,  # 实际是否联网由 dispatcher 依 provider 判定
    layer="②",
)


def _size_for(ctx, params: dict, mode: str) -> tuple[int, int]:
    # 生成尺寸与渠道规格解耦：渠道尺寸由 postprocess 裁切/缩放，生成只负责出底图。
    if params.get("width") and params.get("height"):
        return int(params["width"]), int(params["height"])
    if getattr(ctx.provider, "name", "") == "seedream":
        # Seedream 只支持固定档位（如 1024x1024），渠道尺寸留给后处理。
        return 1024, 1024
    default = 512 if mode == "draft" else 1024
    return default, default


def _steps_for(ctx, params: dict, mode: str) -> int:
    if params.get("steps"):
        return int(params["steps"])
    return 8 if mode == "draft" else 28


def handler(params: dict, ctx, confirmed: bool) -> dict:
    from ..core.scheduler import JobCancelled

    mode = params["mode"]
    prompt = params["prompt"]
    anchor_id = params.get("anchor_id", "")
    seed = int(params.get("seed", 0))
    count = int(params.get("count", 4))
    width, height = _size_for(ctx, params, mode)
    steps = _steps_for(ctx, params, mode)
    model = params.get("model", "")

    # 从 checkpoint 续跑：跳过已完成的前 N 张，复用其资产 id
    resume = params.get("resume") or {}
    start = int(resume.get("done", 0))
    asset_ids: list[str] = list(resume.get("asset_ids", []))
    degraded = []

    for i in range(start, count):
        if ctx.is_cancelled and ctx.is_cancelled():
            raise JobCancelled()
        cur_seed = seed + i
        key = ctx.project.generation_cache_key(prompt, cur_seed, model or "stub", anchor_id)
        if key in ctx.cache and ctx.cache[key] not in asset_ids:
            asset_ids.append(ctx.cache[key])
            continue
        image = _generate_with_degradation(ctx, prompt=prompt, mode=mode, seed=cur_seed,
                                           width=width, height=height, steps=steps,
                                           model=model, anchor_refs=[anchor_id] if anchor_id else None)
        if image.meta.get("degraded"):
            degraded.append(image.meta["degraded"])
        cid = ctx.assets.put(image.data, {"kind": "generated", "prompt": prompt,
                                          "seed": cur_seed, "mode": mode,
                                          **image.meta})
        ctx.cache[key] = cid
        asset_ids.append(cid)
        # step 边界 checkpoint：每完成一张写一次，崩溃后可从下一张续跑
        if ctx.checkpoint:
            ctx.checkpoint({"done": i + 1, "asset_ids": asset_ids[:],
                            "seed": seed, "count": count})

    node_id = params.get("node_id")
    if node_id:
        ctx.project.set_status(node_id, "done", {"asset_ids": asset_ids, "degraded": degraded})
        ctx.project.invalidate_downstream(node_id)

    return {"asset_ids": asset_ids, "mode": mode, "model": model or "stub",
            "degraded": degraded, "count": len(asset_ids)}


def _generate_with_degradation(ctx, *, prompt, mode, seed, width, height, steps, model, anchor_refs):
    """生成 + 重试 + 降级链。"""
    attempts = [
        {"width": width, "height": height, "steps": steps, "model": model, "degraded": None},
    ]
    # 降级链（取自 config/scheduling.yaml）：降分辨率 → 降步数 → 换轻量模型
    chain = ctx.config.get("degradation", {}).get("chain", [])
    if "reduce_resolution" in chain:
        attempts.append({"width": max(256, width // 2), "height": max(256, height // 2),
                         "steps": steps, "model": model, "degraded": "reduce_resolution"})
    if "reduce_steps" in chain:
        attempts.append({"width": width, "height": height, "steps": max(1, steps // 2),
                         "model": model, "degraded": "reduce_steps"})
    if "switch_lighter_model" in chain:
        attempts.append({"width": width, "height": height, "steps": steps,
                         "model": _lighter_model(ctx, model), "degraded": "switch_lighter_model"})

    last_exc: Exception | None = None
    for attempt in attempts:
        for retry in range(2):  # 失败自动重试 1 次
            try:
                img = ctx.provider.generate(
                    prompt=prompt, mode=mode, seed=seed,
                    width=attempt["width"], height=attempt["height"],
                    steps=attempt["steps"], model=attempt["model"] or "",
                    anchor_refs=anchor_refs,
                )
                img.meta["degraded"] = attempt["degraded"]
                return img
            except Exception as exc:  # noqa: BLE001 - 逐级降级，不静默
                last_exc = exc
    raise RuntimeError(f"生成失败（已重试并降级）: {last_exc}")


def _lighter_model(ctx, model: str) -> str:
    registry = ctx.config.get("model_registry", {})
    drafts = registry.get("draft", [])
    if drafts:
        return drafts[0].get("id", "sdxl-lightning")
    return model


_TOOL.handler = handler
register(_TOOL)
