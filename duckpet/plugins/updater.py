"""插件更新器：检查 configs/plugins.toml 里登记的上游开源组件是否有更新。

无第三方依赖（urllib + tomllib）。GitHub API 未登录限流 60 次/小时，
对 20 来个仓库的检查够用。
"""

from __future__ import annotations

import json
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PLUGINS_TOML = Path("configs/plugins.toml")


@dataclass
class UpdateInfo:
    name: str
    capability: str
    repo: str
    pinned: str
    latest_release: str | None
    latest_commit: str | None
    has_update: bool


def _gh_api(path: str) -> dict | list | None:
    import os

    headers = {"Accept": "application/vnd.github+json", "User-Agent": "duckpet-updater"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"   # 限流从 60/小时 提到 5000/小时
    req = urllib.request.Request(f"https://api.github.com/{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001 - 网络失败不应中断整体检查
        print(f"  [警告] 查询失败 {path}: {e}")
        return None


def check_updates(plugins_path: Path = PLUGINS_TOML) -> list[UpdateInfo]:
    data = tomllib.loads(plugins_path.read_text(encoding="utf-8"))
    infos: list[UpdateInfo] = []
    for p in data.get("plugin", []):
        repo = p.get("repo")
        if not repo or "/" not in repo:
            continue
        rel = _gh_api(f"repos/{repo}/releases/latest")
        latest_release = rel.get("tag_name") if isinstance(rel, dict) else None
        commits = _gh_api(f"repos/{repo}/commits?per_page=1")
        latest_commit = None
        if isinstance(commits, list) and commits:
            latest_commit = commits[0].get("sha", "")[:8]
        pinned = p.get("pinned", "")
        has_update = bool(
            (latest_release and pinned and latest_release != pinned)
            or (latest_commit and pinned and not pinned.startswith(latest_commit)
                and not latest_commit.startswith(pinned))
        )
        infos.append(UpdateInfo(
            name=p.get("name", repo),
            capability=p.get("capability", "?"),
            repo=repo,
            pinned=pinned or "(未固定)",
            latest_release=latest_release,
            latest_commit=latest_commit,
            has_update=has_update,
        ))
    return infos


def apply_updates(plugins_path: Path, infos: list[UpdateInfo]) -> None:
    text = plugins_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    out: list[str] = []
    current_repo = None
    pin_of = {i.repo: (i.latest_release or i.latest_commit) for i in infos if i.has_update}
    for line in lines:
        if line.strip().startswith("repo = "):
            current_repo = line.split('"')[1]
        if line.strip().startswith("pinned = ") and current_repo in pin_of:
            indent = line[: len(line) - len(line.lstrip())]
            line = f'{indent}pinned = "{pin_of[current_repo]}"'
        out.append(line)
    plugins_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def report(infos: list[UpdateInfo]) -> str:
    rows = ["能力 | 组件 | 当前 pinned | 最新 release | 最新 commit | 有更新",
            "---|---|---|---|---|---"]
    for i in infos:
        rows.append(
            f"{i.capability} | {i.name} | {i.pinned} | "
            f"{i.latest_release or '-'} | {i.latest_commit or '-'} | "
            f"{'✅ 是' if i.has_update else '否'}"
        )
    return "\n".join(rows)
