#!/usr/bin/env bash
# proxy001 一键注册机 —— Linux / macOS 远程一键脚本
#
# 用法（无需先下载仓库）：
#   bash <(curl -fsSL https://raw.githubusercontent.com/zhacha222/proxy001-register/main/install-linux.sh)
#
# 或指定仓库分支/目录：
#   REPO=zhacha222/proxy001-register BRANCH=main \
#     bash <(curl -fsSL https://raw.githubusercontent.com/zhacha222/proxy001-register/main/install-linux.sh)
#
# 脚本会：检测 python -> 建虚拟环境 -> 装依赖 -> 下载代码 -> 启动交互界面
set -euo pipefail

REPO="${REPO:-zhacha222/proxy001-register}"
BRANCH="${BRANCH:-main}"
WORKDIR="${WORKDIR:-$HOME/.proxy001-register}"

BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; RESET=""
if [ -t 1 ]; then
    BOLD=$'\033[1m'; DIM=$'\033[90m'; RED=$'\033[31m'
    GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
fi

say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s⚠%s %s\n' "$YELLOW" "$RESET" "$*"; }
die()  { printf '%s✗%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

say "${BOLD}========================================================${RESET}"
say "${BOLD}  proxy001 一键注册机  ·  远程安装器${RESET}"
say "${BOLD}========================================================${RESET}"
say ""

# ---------- 1. 找 python ----------
PY=""
for cand in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c 'import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)' 2>/dev/null; then
            PY="$cand"; break
        fi
    fi
done
[ -n "$PY" ] || die "找不到 Python 3.8+。请先安装：
  Debian/Ubuntu:  sudo apt update && sudo apt install -y python3 python3-venv python3-pip
  CentOS/RHEL:    sudo dnf install -y python3 python3-pip
  Alpine:         sudo apk add python3 py3-pip py3-virtualenv
  macOS:          brew install python3"
ok "Python: $($PY -V 2>&1)  ($(command -v "$PY"))"

# ---------- 2. venv（可选，失败则用 --user） ----------
mkdir -p "$WORKDIR"
VENV="$WORKDIR/venv"
PYRUN="$PY"

if "$PY" -m venv --help >/dev/null 2>&1; then
    if [ ! -x "$VENV/bin/python" ]; then
        say "${DIM}[*] 创建虚拟环境 $VENV${RESET}"
        if ! "$PY" -m venv "$VENV" 2>/dev/null; then
            warn "venv 创建失败（可能缺 python3-venv），改用当前环境"
            VENV=""
        fi
    fi
    [ -n "$VENV" ] && PYRUN="$VENV/bin/python"
else
    warn "当前 Python 不支持 venv，改用当前环境"
    VENV=""
fi
ok "解释器: $PYRUN"

# ---------- 3. 下载代码 ----------
if [ -f "$WORKDIR/run.py" ] && [ "${FORCE_UPDATE:-0}" != "1" ]; then
    say "${DIM}[*] 已存在代码目录，跳过下载（FORCE_UPDATE=1 可强制更新）${RESET}"
else
    say "${DIM}[*] 下载代码 $REPO@$BRANCH${RESET}"
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    GOT=0
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" -o "$TMP/repo.tgz" && GOT=1
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$TMP/repo.tgz" "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" && GOT=1
    fi
    [ "$GOT" = "1" ] || die "下载失败，检查网络或仓库名（$REPO / $BRANCH）"

    tar -xzf "$TMP/repo.tgz" -C "$TMP"
    SRC="$(find "$TMP" -maxdepth 1 -type d -name '*-*' | head -1)"
    [ -n "$SRC" ] || die "解包后找不到源码目录"
    rm -rf "$WORKDIR/src"
    mkdir -p "$WORKDIR/src"
    cp -a "$SRC"/. "$WORKDIR/src"/
    ok "代码已就位: $WORKDIR/src"
fi

cd "$WORKDIR/src"

# ---------- 4. 装依赖 ----------
say "${DIM}[*] 检查依赖${RESET}"
if ! "$PYRUN" -c 'import requests, cryptography' >/dev/null 2>&1; then
    say "${DIM}[*] 安装 requests + cryptography${RESET}"
    "$PYRUN" -m pip install -q --upgrade pip 2>/dev/null || true
    if ! "$PYRUN" -m pip install -q -r requirements.txt; then
        warn "常规安装失败，尝试 --user"
        "$PYRUN" -m pip install -q --user -r requirements.txt \
            || die "依赖安装失败，请手动执行: $PYRUN -m pip install requests cryptography"
    fi
fi
"$PYRUN" -c 'import requests, cryptography' || die "依赖校验失败"
ok "依赖就绪"

# ---------- 5. 启动 ----------
say ""
say "${BOLD}========================================================${RESET}"
say "${BOLD}  启动交互界面${RESET}"
say "${BOLD}========================================================${RESET}"
say ""

exec "$PYRUN" run.py "$@"
