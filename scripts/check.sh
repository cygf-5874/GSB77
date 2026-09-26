#!/usr/bin/env bash
# 固定验收入口的薄封装：把参数原样转给仓库根的 check.py。
#
#   bash scripts/check.sh              # 跑全部 11 个场景
#   bash scripts/check.sh -list        # 列出全部场景
#   bash scripts/check.sh --only layout
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if command -v python3 >/dev/null 2>&1; then
  exec python3 check.py "$@"
fi
exec python check.py "$@"
