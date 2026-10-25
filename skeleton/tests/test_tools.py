from pathlib import Path

import pytest
from PIL import Image

from aiside.errors import ConfirmationRequired


def _sample_images(tmp_path, n=2):
    paths = []
    for i in range(n):
        img = Image.new("RGB", (512, 512), (200 + i * 10, 180, 160))
        p = tmp_path / f"s{i}.png"
        img.save(p)
        paths.append(str(p))
    return paths


def test_ingest_tool(workspace, tmp_path):
    ctx = workspace.create_project()
    paths = _sample_images(tmp_path)
    result = workspace.dispatcher.dispatch(
        "ingest_and_qa_photos", {"image_paths": paths, "sku_id": "s1"}, ctx)
    assert len(result["passed"]) == 2
    assert all(r["qa"]["ok"] for r in result["items"])


def test_anchor_and_generate_and_score(workspace, tmp_path):
    ctx = workspace.create_project()
    paths = _sample_images(tmp_path)
    ingest = workspace.dispatcher.dispatch(
        "ingest_and_qa_photos", {"image_paths": paths}, ctx)
    photo_ids = [r["source_asset_id"] for r in ingest["items"]]

    anchor = workspace.dispatcher.dispatch(
        "build_consistency_anchor", {"photo_ids": photo_ids}, ctx)
    gen = workspace.dispatcher.dispatch(
        "generate_image",
        {"mode": "draft", "prompt": "白底主图", "seed": 1, "count": 3,
         "anchor_id": anchor["anchor_asset_id"]},
        ctx)
    assert len(gen["asset_ids"]) == 3

    score = workspace.dispatcher.dispatch(
        "score_fidelity_and_batch_qa",
        {"asset_ids": gen["asset_ids"], "anchor_id": anchor["anchor_asset_id"]},
        ctx)
    assert 0.0 <= score["batch_consistency"] <= 1.0
    assert len(score["fidelity"]) == 3


def test_generate_cache_hit(workspace, tmp_path):
    ctx = workspace.create_project()
    paths = _sample_images(tmp_path, 1)
    ingest = workspace.dispatcher.dispatch(
        "ingest_and_qa_photos", {"image_paths": paths}, ctx)
    anchor = workspace.dispatcher.dispatch(
        "build_consistency_anchor", {"photo_ids": [r["source_asset_id"] for r in ingest["items"]]}, ctx)
    params = {"mode": "draft", "prompt": "p", "seed": 9, "count": 2, "anchor_id": anchor["anchor_asset_id"]}
    first = workspace.dispatcher.dispatch("generate_image", params, ctx)
    second = workspace.dispatcher.dispatch("generate_image", params, ctx)
    assert first["asset_ids"] == second["asset_ids"]


def test_postprocess_requires_confirmation(workspace, tmp_path):
    ctx = workspace.create_project()
    paths = _sample_images(tmp_path, 1)
    ingest = workspace.dispatcher.dispatch(
        "ingest_and_qa_photos", {"image_paths": paths}, ctx)
    anchor = workspace.dispatcher.dispatch(
        "build_consistency_anchor", {"photo_ids": [r["source_asset_id"] for r in ingest["items"]]}, ctx)
    gen = workspace.dispatcher.dispatch(
        "generate_image", {"mode": "draft", "prompt": "p", "seed": 3, "count": 1,
                           "anchor_id": anchor["anchor_asset_id"], "channel": "douyin"}, ctx)

    params = {"asset_id": gen["asset_ids"][0], "channels": ["douyin"],
              "output_dir": str(tmp_path / "out"), "sku_id": "s1"}
    with pytest.raises(ConfirmationRequired):
        workspace.dispatcher.dispatch("postprocess_and_package", params, ctx)
    result = workspace.dispatcher.dispatch("postprocess_and_package", params, ctx, confirmed=True)
    # 抖音 4 个规格：商品主图1 + 场景主图1 + 详情页3屏 + 商品卡1 = 6
    assert len(result["files"]) == 6
    detail = [f for f in result["files"] if f["spec"] == "detail"]
    assert len(detail) == 3
    assert Path(result["manifest"]).exists()


def test_unregistered_tool_denied(workspace):
    ctx = workspace.create_project()
    with pytest.raises(KeyError):
        workspace.dispatcher.dispatch("not_a_tool", {}, ctx)
