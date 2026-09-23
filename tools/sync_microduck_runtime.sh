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

# 重打 Windows 兼容补丁（termios/tty 是 Unix 专属，KeyboardReader 置 None 禁用）——幂等
python3 - <<'PYEOF'
import pathlib
p = pathlib.Path("third_party/microduck_runtime/scripts/infer_policy.py")
src = p.read_text(encoding="utf-8")
if "[DuckPet 补丁]" in src:
    print("[同步] Windows 兼容补丁已在，跳过")
else:
    old_imports = "import select\nimport sys\nimport termios\nimport threading\nimport time\nimport tty\n"
    new_imports = (
        "import select\nimport sys\nimport threading\nimport time\n"
        "# [DuckPet 补丁] termios/tty 是 Unix 专用；Windows 导入即崩。\n"
        "# 仅 KeyboardReader（键盘遥控）用到，置 None 后该类自动禁用，\n"
        "# PolicyInference 等核心功能不受影响。此补丁由 tools/sync_microduck_runtime.sh\n"
        "# 在每次从上游重新裁剪后自动重打（幂等）。\n"
        "try:\n    import termios\n    import tty\nexcept ImportError:  # Windows\n"
        "    termios = None\n    tty = None\n")
    assert old_imports in src, "上游 import 布局变了，需手工核对补丁"
    src = src.replace(old_imports, new_imports, 1)
    old_init = "        self.enabled = sys.stdin.isatty()\n"
    new_init = ("        # [DuckPet 补丁] termios 为 None 的平台（Windows）禁用键盘遥控\n"
                "        self.enabled = sys.stdin.isatty() and termios is not None\n")
    assert old_init in src, "上游 KeyboardReader 布局变了，需手工核对补丁"
    src = src.replace(old_init, new_init, 1)
    p.write_text(src, encoding="utf-8")
    print("[同步] 已重打 Windows 兼容补丁（termios/tty guard）")
PYEOF
# scene_ball.xml 闭包：robot_groundcontact.xml / ball.xml 引用的全部 STL
grep -hoE 'file="[^"]*\.stl"' "$RT/$ROBOT/robot_groundcontact.xml" "$RT/$ROBOT/ball.xml" \
  | sed 's/file="//;s/"//' | sort -u | while read -r f; do
    cp "$SRC/$ROBOT/assets/$f" "$RT/$ROBOT/assets/$f"
done
cp "$SRC/LICENSE" "$RT/LICENSE"

REV=$(git -C "$SRC" rev-parse --short HEAD)
BRANCH=$(git -C "$SRC" branch --show-current)
sed -i '' -E "s/上游版本：\`[^\`]*\` 分支 \`[^\`]*\`（[^）]*）/上游版本：\`$BRANCH\` 分支 \`$REV\`（$(date +%Y-%m-%d) 裁剪）/" "$RT/README.md"
echo "已同步 $BRANCH@$REV → ${RT}（$(find "$RT" -type f | wc -l | tr -d ' ') 个文件）"
