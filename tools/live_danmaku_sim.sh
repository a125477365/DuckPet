#!/bin/bash
# 直播模式一键启动（macOS）：打开直播伴侣 + 3D 物理仿真鸭（弹幕桥内嵌线程）。
#
#   bash tools/live_danmaku_sim.sh                # 只转发像指令的弹幕
#   bash tools/live_danmaku_sim.sh --all          # 转发所有弹幕
#   bash tools/live_danmaku_sim.sh --region 0.66,0.30,0.32,0.45
#
# 弹幕桥现在是仿真内线程（--danmaku），不再是独立进程管道：
# 评论区弹幕和终端键盘输入同时生效。退出：Ctrl+C。
# Windows 用 tools/live_danmaku_sim.bat。
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
    || echo "[启动] 没找到直播伴侣 app，请手动打开（弹幕桥会每 5 秒重试找窗口）"
fi

# 旧参数翻译成 --danmaku-* 传给仿真
ARGS=(--danmaku)
while [ $# -gt 0 ]; do
  case "$1" in
    --all)      ARGS+=(--danmaku-all);;
    --region)   ARGS+=(--danmaku-region "$2"); shift;;
    --region=*) ARGS+=(--danmaku-region "${1#*=}");;
    --app)      ARGS+=(--danmaku-app "$2"); shift;;
    --app=*)    ARGS+=(--danmaku-app "${1#*=}");;
    --interval) ARGS+=(--danmaku-interval "$2"); shift;;
    --interval=*) ARGS+=(--danmaku-interval "${1#*=}");;
    *)          ARGS+=("$1");;
  esac
  shift
done

echo "[启动] 3D 仿真 + 弹幕桥线程（首次运行请确认：系统设置→隐私与安全性→屏幕录制 已勾选本终端）"
exec bash tools/sim_duckpet_3d.sh "${ARGS[@]}"
