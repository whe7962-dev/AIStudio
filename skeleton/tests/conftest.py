import sys
from pathlib import Path

import pytest

# 让 tests 能 import aiside（skeleton 根目录）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiside.settings import ROOT_DIR, Settings  # noqa: E402
from aiside.workspace import Workspace  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path / "data",
        config_dir=ROOT_DIR / "config",
        provider="stub",
    )


@pytest.fixture
def workspace(settings):
    ws = Workspace(settings)
    yield ws
    ws.close()
