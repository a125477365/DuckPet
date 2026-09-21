"""检查 configs/plugins.toml 中登记的上游开源组件是否有更新。

  python3 tools/update_plugins.py          # 只报告
  python3 tools/update_plugins.py --apply  # 把最新版本号写回 plugins.toml 的 pinned
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from duckpet.plugins.updater import PLUGINS_TOML, apply_updates, check_updates, report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="把最新版本写回 plugins.toml")
    args = ap.parse_args()

    print("正在检查上游更新（GitHub API，未登录限流 60 次/小时）……")
    infos = check_updates(PLUGINS_TOML)
    print(report(infos))
    updates = [i for i in infos if i.has_update]
    if not updates:
        print("\n所有已固定组件都是最新的。pinned 为空的条目表示尚未锁定版本。")
        return
    print(f"\n有 {len(updates)} 个组件可更新。")
    if args.apply:
        apply_updates(PLUGINS_TOML, infos)
        print("已写回 plugins.toml。pip 类组件请再执行：")
        for i in updates:
            print(f"  # {i.name}\n  pip install -U <对应包，见 plugins.toml package 字段>")
    else:
        print("加 --apply 写回锁定版本。")


if __name__ == "__main__":
    main()
