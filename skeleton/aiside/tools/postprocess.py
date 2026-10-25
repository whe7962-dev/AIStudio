"""P6 后处理与导出：postprocess_and_package。

红线：导出前必须用户确认（permission=ask + 破坏性）。未确认一律不落盘。
骨架阶段实现裁切（中心裁切 + 缩放）、命名、格式、打包清单；文字/水印留扩展点。
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image

from .registry import register, Tool

_TOOL = Tool(
    name="postprocess_and_package",
    description="按渠道规格裁切/命名/打包成素材包；导出前需用户确认。",
    json_schema={
        "type": "object",
        "properties": {
            "asset_id": {"type": "string"},
            "channels": {"type": "array", "items": {"type": "string"}},
            "output_dir": {"type": "string"},
            "sku_id": {"type": "string"},
            "watermark_text": {"type": "string"},
            "node_id": {"type": "string"},
        },
        "required": ["asset_id", "channels", "output_dir"],
    },
    permission="ask",
    destructive=True,
    network=False,
    layer="⑥",
)


def _fit(img: Image.Image, width: int, height: int) -> Image.Image:
    # 中心裁切到目标宽高比后缩放
    target_ratio = width / height
    src_ratio = img.width / img.height
    if src_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        left = (img.width - new_w) // 2
        box = (left, 0, left + new_w, img.height)
    else:
        new_h = int(img.width / target_ratio)
        top = (img.height - new_h) // 2
        box = (0, top, img.width, top + new_h)
    return img.crop(box).resize((width, height), Image.LANCZOS)


def handler(params: dict, ctx, confirmed: bool) -> dict:
    if not confirmed:
        # 权限层应已拦截；这里双保险：未确认绝不落盘
        raise PermissionError("导出前必须用户确认，未确认不落盘")

    output_dir = Path(params["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    naming = ctx.config.get("naming", {})
    template = naming.get("template", "{sku_id}_{channel_id}_{spec_id}{suffix}.{format}")
    sku_id = params.get("sku_id", "sku")
    watermark_text = params.get("watermark_text", naming.get("watermark_text", ""))

    source = Image.open(io.BytesIO(ctx.assets.get(params["asset_id"])))
    files = []
    spec_ok = True
    spec_reasons = []
    channel_specs = {ch["id"]: ch for ch in ctx.channels}

    for channel_id in params["channels"]:
        ch = channel_specs.get(channel_id)
        if ch is None:
            spec_ok = False
            spec_reasons.append(f"未知渠道: {channel_id}")
            continue
        for spec in ch["specs"]:
            fmt = spec.get("format", "jpg").lower()
            # 详情页等「多屏」规格：按 min_count 出多张（内容复用，真实分屏由后续硬化）
            count = max(1, int(spec.get("min_count", 1)))
            for idx in range(count):
                suffix = spec.get("suffix", "")
                if count > 1:
                    suffix += f"_p{idx + 1}"
                out_img = _fit(source, spec["width"], spec["height"])
                if watermark_text:
                    from PIL import ImageDraw
                    draw = ImageDraw.Draw(out_img)
                    draw.text((8, 8), watermark_text, fill=(255, 255, 255))
                filename = template.format(
                    sku_id=sku_id, channel_id=channel_id, spec_id=spec["id"],
                    suffix=suffix, format=fmt)
                out_path = output_dir / filename
                out_img.convert("RGB").save(out_path, format="JPEG" if fmt == "jpg" else fmt.upper())
                files.append({"file": str(out_path), "channel": channel_id, "spec": spec["id"],
                              "index": idx + 1, "size": f"{spec['width']}x{spec['height']}"})

    manifest = {"files": files, "spec_check": {"passed": spec_ok, "reasons": spec_reasons},
                "watermark_text": watermark_text}
    manifest_path = output_dir / naming.get("manifest_filename", "manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    node_id = params.get("node_id")
    if node_id:
        ctx.project.set_status(node_id, "done", {"package_dir": str(output_dir),
                                                 "files": files, "spec_ok": spec_ok})

    return {"package_dir": str(output_dir), "files": files,
            "spec_check": manifest["spec_check"], "manifest": str(manifest_path)}


_TOOL.handler = handler
register(_TOOL)
