#!/usr/bin/env bash
# proxy001 一键注册机 —— Linux / macOS 启动器
set -euo pipefail
cd "$(dirname "$0")"

echo "========================================================"
echo "  proxy001 一键注册机"
echo "========================================================"
echo

PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        PY="$cand"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "[错误] 找不到 python，请先安装 Python 3.8+"
    exit 1
fi

echo "[*] 检查依赖..."
if ! "$PY" -c "import requests, cryptography" >/dev/null 2>&1; then
    echo "[*] 首次运行，安装依赖..."
    "$PY" -m pip install -r requirements.txt
fi

echo
exec "$PY" run.py "$@"
