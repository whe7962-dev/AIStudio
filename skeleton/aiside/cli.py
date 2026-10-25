"""命令行入口。

  python -m aiside demo     离线跑通电商闭环（stub provider，无需密钥）
  python -m aiside serve    启动本地 HTTP 服务
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aiside", description="端侧AIStudio 后端骨架")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("demo", help="离线跑通电商闭环（stub provider）")
    sub.add_parser("serve", help="启动本地 HTTP 服务")

    args = parser.parse_args(argv)

    if args.command == "demo":
        from .pipeline import run_ecommerce_demo
        result = run_ecommerce_demo()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "serve":
        import uvicorn
        from .settings import get_settings
        settings = get_settings()
        uvicorn.run("aiside.main:app", host=settings.host, port=settings.port, reload=False)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
