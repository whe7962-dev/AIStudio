from aiside.pipeline import run_ecommerce_demo


def test_ecommerce_demo_end_to_end(workspace, tmp_path):
    result = run_ecommerce_demo(settings=workspace.settings, workspace=workspace,
                                output_dir=tmp_path / "exports")
    assert result["project_id"]
    assert len(result["files"]) >= 1
    assert 0.0 <= result["batch_consistency"] <= 1.0
    assert all(t["status"] == "done" for t in result["todo"])
