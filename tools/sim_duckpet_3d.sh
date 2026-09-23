#!/bin/bash
# 启动 DuckPet 自主鸭 3D 仿真：DuckPet 大脑（乱逛/听声找人/优先级仲裁/
# 踢球/叼东西）驱动 microduck 官方 MuJoCo 物理仿真。不是键盘遥控——
# 鸭子自己活着，你在终端里用文字指令和它互动（help 查看指令）。
#
# 用法：
#   bash tools/sim_duckpet_3d.sh            # 3D 窗口 + 终端文字指令
#   bash tools/sim_duckpet_3d.sh --headless # 无窗口自动验证（CI 友好）
cd "$(dirname "$0")/.." || exit 1

VENV=third_party/microduck_rl/.venv-sim
if [ ! -d "$VENV" ]; then
    echo "模拟器环境还没装，正在安装（仅需一次）……"
    UV=$(command -v uv || echo ~/.local/bin/uv)
    "$UV" venv "$VENV" --python 3.12
    "$UV" pip install --python "$VENV" \
        mujoco onnxruntime numpy better-actuator-models glfw
fi

if [ "${1:-}" = "--headless" ]; then
    exec "$VENV/bin/python" tools/sim_duckpet_3d.py "$@"
fi

# macOS 上 MuJoCo viewer 需要 mjpython（主线程留给 Cocoa）。
# 标准 mjpython 入口依赖 otool（Xcode 命令行工具），这里直接手动设置
# MJPYTHON_BIN / MJPYTHON_LIBPYTHON 环境变量再 exec 原生跳板二进制，
# 效果等同 mjpython 但不需要 Xcode。
SITE="$PWD/$VENV/lib/python3.12/site-packages"
MJPYAPP="$SITE/mujoco/MuJoCo_(mjpython).app/Contents/MacOS/mjpython"
VENVPY="$PWD/$VENV/bin/python"

# 关键：不设置这个变量时，glfw 包会用 sys.executable 开子进程探测 dylib
# 版本，而跳板里 sys.executable 是 mjpython 二进制——每个探测子进程又会
# 触发 mjpython 引导（它自己也 import glfw），递归 fork 直到耗尽进程表
#（BlockingIOError: Errno 35）。指定 PYGLFW_LIBRARY 后 glfw 直接 dlopen，
# 完全跳过子进程探测。
export PYGLFW_LIBRARY="$SITE/glfw/libglfw.3.dylib"

export MJPYTHON_BIN="$MJPYAPP"
export MJPYTHON_LIBPYTHON="$VENVPY"
export PYTHONPATH="$SITE"

# mjpython 二进制的 argv 约定（见 mujoco 自带 mjpython.py 第 94-96 行）：
# argv[0]=python 解释器路径，argv[1]=用户脚本。用 exec -a 把 argv[0]
# 设成 venv 的 python，否则它会把 argv[1] 的 python 二进制当脚本解析。
exec -a "$VENVPY" "$MJPYAPP" tools/sim_duckpet_3d.py "$@"
