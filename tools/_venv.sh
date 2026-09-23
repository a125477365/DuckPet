#!/bin/bash
# 公共函数：仿真 venv 的创建与装包。被 tools/*.sh source，不单独运行。
#
# 依赖安装器：优先 uv（快、会自动装 Python 3.12）；
# 没有 uv 就回退系统 Python 自带的 venv+pip（要求 3.10+，3.12 最稳）。

SIM_VENV=third_party/microduck_rl/.venv-sim

UV=""
if command -v uv >/dev/null 2>&1; then UV=uv
elif [ -x ~/.local/bin/uv ]; then UV=~/.local/bin/uv
fi

venv_create() {  # venv_create <目录>
    if [ -n "$UV" ]; then "$UV" venv "$1" --python 3.12; return; fi
    local PY=""
    for c in python3.12 python3.13 python3.11 python3.10 python3; do
        if command -v "$c" >/dev/null 2>&1 \
           && "$c" -c 'import sys; sys.exit(sys.version_info < (3,10))' 2>/dev/null; then
            PY=$c; break
        fi
    done
    if [ -z "$PY" ]; then
        echo "[错误] 没找到 uv 也没找到 >=3.10 的 Python。"
        echo "  装 uv：https://docs.astral.sh/uv/ ；或装 Python 3.12：https://www.python.org/downloads/"
        return 1
    fi
    echo "[提示] 没找到 uv，用系统 $PY 建 venv（装 uv 会更快）"
    "$PY" -m venv "$1"
}

venv_pip() {  # venv_pip <venv目录> <包...>
    if [ -n "$UV" ]; then "$UV" pip install --python "$1" "${@:2}"
    else "$1/bin/python" -m pip install "${@:2}"; fi
}

ensure_sim_venv() {  # 确保仿真 venv 存在且基础依赖已装
    if [ ! -d "$SIM_VENV" ]; then
        echo "模拟器环境还没装，正在安装（仅需一次）……"
        venv_create "$SIM_VENV" || return 1
        venv_pip "$SIM_VENV" mujoco onnxruntime numpy better-actuator-models glfw || return 1
    fi
}
