#!/bin/bash
# 把 third_party/microduck_rl（完整子模块）里跑仿真必需的文件
# 重新裁剪到 third_party/microduck_runtime/（仓库内置副本）。
# 上游子模块升级后（git submodule update --remote）运行一次即可。
set -eu
cd "$(dirname "$0")/.."
SRC=third_party/microduck_rl
RT=third_party/microduck_runtime
ROBOT=src/mjlab_microduck/robot/microduck

if [ ! -f "$SRC/scripts/infer_policy.py" ]; then
    echo "子模块还没初始化：git submodule update --init --depth 1 third_party/microduck_rl"
    exit 1
fi

mkdir -p "$RT/scripts" "$RT/$ROBOT/assets"
cp "$SRC/scripts/infer_policy.py" "$RT/scripts/"
cp "$SRC/$ROBOT/scene_ball.xml" "$SRC/$ROBOT/robot_groundcontact.xml" "$SRC/$ROBOT/ball.xml" \
   "$RT/$ROBOT/"
# scene_ball.xml 闭包：robot_groundcontact.xml / ball.xml 引用的全部 STL
grep -hoE 'file="[^"]*\.stl"' "$RT/$ROBOT/robot_groundcontact.xml" "$RT/$ROBOT/ball.xml" \
  | sed 's/file="//;s/"//' | sort -u | while read -r f; do
    cp "$SRC/$ROBOT/assets/$f" "$RT/$ROBOT/assets/$f"
done
cp "$SRC/LICENSE" "$RT/LICENSE"

REV=$(git -C "$SRC" rev-parse --short HEAD)
BRANCH=$(git -C "$SRC" branch --show-current)
sed -i '' -E "s/上游版本：\`[^\`]*\` 分支 \`[^\`]*\`（[^）]*）/上游版本：\`$BRANCH\` 分支 \`$REV\`（$(date +%Y-%m-%d) 裁剪）/" "$RT/README.md"
echo "已同步 $BRANCH@$REV → $RT（$(find "$RT" -type f | wc -l | tr -d ' ') 个文件）"
