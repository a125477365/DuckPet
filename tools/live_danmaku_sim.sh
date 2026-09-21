#!/bin/bash
# 直播模式一键启动：打开直播伴侣 + 3D 物理仿真鸭 + 评论区弹幕桥。
#
#   bash tools/live_danmaku_sim.sh                # 只转发像指令的弹幕
#   bash tools/live_danmaku_sim.sh --all          # 转发所有弹幕
#   bash tools/live_danmaku_sim.sh --region 0.66,0.30,0.32,0.45
#
# 其他参数原样传给 tools/live_companion_danmaku.py（--interval/--ignore/--app…）。
# 退出：Ctrl+C（弹幕桥和仿真会一起退出）。
set -u
cd "$(dirname "$0")/.."
PY=third_party/microduck_rl/.venv-sim/bin/python

if ! "$PY" -c "import Vision, Quartz" 2>/dev/null; then
  echo "[启动] 安装 OCR 依赖（pyobjc Vision/Quartz）…"
  (cd third_party/microduck_rl && uv pip install --python .venv-sim/bin/python \
    pyobjc-framework-Vision pyobjc-framework-Quartz pyobjc-framework-Cocoa) || exit 1
fi

if ! pgrep -f "Douyin Webcast Mate" >/dev/null && ! pgrep -f "直播伴侣" >/dev/null; then
  echo "[启动] 打开直播伴侣…"
  open -a "Douyin Webcast Mate" 2>/dev/null || open -a "直播伴侣" 2>/dev/null \
    || echo "[启动] 没找到直播伴侣 app，请手动打开"
fi

echo "[启动] 弹幕桥 → 3D 仿真（首次运行请确认：系统设置→隐私与安全性→屏幕录制 已勾选本终端）"
"$PY" tools/live_companion_danmaku.py "$@" | bash tools/sim_duckpet_3d.sh
