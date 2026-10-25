#!/usr/bin/env bash
# 一条命令启动：依赖检查 → 加载 demo-api.env → 运行后端
# 用法：
#   ./scripts/dev.sh demo     离线跑通电商闭环（stub provider，无需密钥）
#   ./scripts/dev.sh serve    启动本地 HTTP 服务（默认 127.0.0.1:8765）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 1) Python 检查
if ! command -v python3 >/dev/null 2>&1; then
  echo "错误：需要 Python 3.10+" >&2
  exit 1
fi

# 2) 虚拟环境 + 依赖（骨架自己的 .venv 建在 skeleton/ 内）
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q -r requirements.txt

# 3) 加载 demo 生图 API key（真实 key 在 ../demo-api.env，不入库、不进 git）
DEMO_ENV="${DEMO_ENV_FILE:-../demo-api.env}"
if [ -f "$DEMO_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$DEMO_ENV"
  set +a
  echo "已加载 demo-api.env（demo 生图通道可用）"
else
  echo "未找到 $DEMO_ENV，使用 stub provider（离线可跑，正式版切本地推理）"
fi

# 4) 运行
CMD="${1:-serve}"
if [ "$CMD" = "demo" ]; then
  python -m aiside demo
else
  python -m aiside serve
fi
