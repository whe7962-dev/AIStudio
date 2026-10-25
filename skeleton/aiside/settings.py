"""配置加载：环境变量 > ../demo-api.env > .env。

红线：真实密钥只从 demo-api.env / 环境变量注入，绝不写进代码、日志、PRD、git。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent                     # skeleton/
PRODUCT_DIR = ROOT_DIR.parent                     # out/端侧AIStudio/
DEFAULT_DEMO_ENV = PRODUCT_DIR / "demo-api.env"


def _load_dotenv_files() -> None:
    # 顺序：先 demo-api.env，再 .env；都不覆盖已存在的环境变量（环境变量优先级最高）。
    demo_env = Path(os.environ.get("DEMO_ENV_FILE", str(DEFAULT_DEMO_ENV)))
    if demo_env.exists():
        load_dotenv(dotenv_path=demo_env, override=False)
    local_env = ROOT_DIR / ".env"
    if local_env.exists():
        load_dotenv(dotenv_path=local_env, override=False)


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: Path = field(default_factory=lambda: ROOT_DIR / "data")
    config_dir: Path = field(default_factory=lambda: ROOT_DIR / "config")
    provider: str = "stub"  # stub | seedream

    # demo 期豆包 Seedream（火山方舟 Ark）
    demo_base_url: str = ""
    demo_api_key: str = ""
    demo_kind: str = "ark"
    demo_model_draft: str = "doubao-seedream-5-0-flash-260915"
    demo_model_final: str = "doubao-seedream-5-0-pro-260628"
    demo_model_edit: str = "doubao-seededit-3-0-i2i-250628"

    # 理解层 LLM（OpenAI 兼容；正式版指向本地 Qwen3，如 Ollama/LM Studio/MLX）
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    network_allowlist: list[str] = field(default_factory=list)

    @property
    def seedream_enabled(self) -> bool:
        return bool(self.demo_base_url and self.demo_api_key)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)

    def allowed_network_domain(self, url: str) -> bool:
        """网络出口白名单：仅放行配置允许的域名。"""
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False
        return any(
            host == item or host.endswith("." + item)
            for item in (d.lower() for d in self.network_allowlist)
        )


def get_settings() -> Settings:
    _load_dotenv_files()
    s = Settings(
        host=os.environ.get("AISIDE_HOST", "127.0.0.1"),
        port=int(os.environ.get("AISIDE_PORT", "8765")),
        data_dir=Path(os.environ.get("AISIDE_DATA_DIR", str(ROOT_DIR / "data"))),
        config_dir=Path(os.environ.get("AISIDE_CONFIG_DIR", str(ROOT_DIR / "config"))),
        demo_base_url=os.environ.get("DEMO_BASE_URL", ""),
        demo_api_key=os.environ.get("DEMO_API_KEY", ""),
        demo_kind=os.environ.get("DEMO_KIND", "ark"),
        demo_model_draft=os.environ.get("DEMO_MODEL_DRAFT", "doubao-seedream-5-0-flash-260915"),
        demo_model_final=os.environ.get("DEMO_MODEL_FINAL", "doubao-seedream-5-0-pro-260628"),
        demo_model_edit=os.environ.get("DEMO_MODEL_EDIT", "doubao-seededit-3-0-i2i-250628"),
        llm_base_url=os.environ.get("LLM_BASE_URL", ""),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_model=os.environ.get("LLM_MODEL", ""),
    )
    # provider 显式指定优先，否则按是否具备 demo key 自动选择
    explicit = os.environ.get("AISIDE_PROVIDER", "").strip().lower()
    if explicit:
        s.provider = explicit
    else:
        s.provider = "seedream" if s.seedream_enabled else "stub"

    # 网络白名单：默认放行 demo 生图 API 域名
    allowlist = [
        d.strip().lower()
        for d in os.environ.get("AISIDE_NETWORK_ALLOWLIST", "").split(",")
        if d.strip()
    ]
    if s.demo_base_url:
        demo_host = urlparse(s.demo_base_url).hostname
        if demo_host and demo_host not in allowlist:
            allowlist.append(demo_host.lower())
    s.network_allowlist = allowlist
    return s
