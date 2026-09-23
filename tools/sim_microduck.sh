#!/bin/bash
# 启动 microduck 官方模拟器（MuJoCo 物理仿真 + 官方预训练策略全家桶）
# 用法：bash tools/sim_microduck.sh
#
# 键盘操作（模拟器启动后也会打印完整说明）：
#   方向键/WASD  行走与转向        K / L   左脚/右脚踢球（自动加载带球场景）
#   G            喙叼地上物体       Y      坐下/站起        R  前滚翻
#   B            身体姿态模式       H      头部控制模式      Q  退出
cd "$(dirname "$0")/.." || exit 1

# 运行时在完整子模块里优先（跟随上游），子模块没初始化用仓库内置副本
if [ -f third_party/microduck_rl/scripts/infer_policy.py ]; then
    RT=third_party/microduck_rl
else
    RT=third_party/microduck_runtime
fi

VENV=third_party/microduck_rl/.venv-sim
if [ ! -d "$VENV" ]; then
    echo "模拟器环境还没装，正在安装（仅需一次）……"
    UV=$(command -v uv || echo ~/.local/bin/uv)
    "$UV" venv "$VENV" --python 3.12
    "$UV" pip install --python "$VENV" \
        mujoco onnxruntime numpy better-actuator-models glfw
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
# 策略文件在项目根 policies/（随仓库自带），场景相对路径要求 cwd=运行时根
cd "$RT" || exit 1
P=../../policies
exec -a "$VENVPY" "$MJPYAPP" scripts/infer_policy.py \
    --walking $P/alpha_walking.onnx \
    --standing $P/alpha_stand.onnx \
    --sitstand $P/alpha_sitstand.onnx \
    --ground-pick $P/alpha_ground_pick.onnx \
    --kick-left $P/ball_kick_left.onnx \
    --kick-right $P/ball_kick_right.onnx \
    --roulade $P/roulade.onnx \
    --new-cmd-obs
