#!/usr/bin/env python3
"""直播弹幕 → DuckPet 指令桥。

自动找到「直播伴侣」（Douyin Webcast Mate）窗口，定时截取评论区，
用 macOS 原生 Vision OCR 识别新评论；像鸭子指令的评论以
「昵称：内容」格式打印到 stdout —— 通过管道喂给
tools/sim_duckpet_3d.sh，走完整的 身份识别→意图解析→优先级仲裁→执行
管线（观众未登记 = 陌生人，跟随等特权指令会被礼貌拒绝）。

用法：
    python3 tools/live_companion_danmaku.py              # 持续监听（先静默建立基线）
    python3 tools/live_companion_danmaku.py --all        # 转发所有评论，不限于指令
    python3 tools/live_companion_danmaku.py --list       # 列出所有窗口（确认 app 名）
    python3 tools/live_companion_danmaku.py --dump       # OCR 整个窗口一次（校准 --region 用）
    python3 tools/live_companion_danmaku.py --region 0.66,0.30,0.32,0.45

注意：macOS 需要在 系统设置 → 隐私与安全性 → 屏幕录制 里勾选你用的终端 App
（Terminal/iTerm/VS Code…），否则截不到窗口内容（会提示但识别结果为空）。
诊断信息打印在 stderr，不会污染喂给鸭子的 stdout。
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import re
import sys
import time
from pathlib import Path

try:
    import Quartz
    import Vision
except ImportError:
    sys.stderr.write(
        "缺少 OCR 依赖。请执行：\n"
        "  cd third_party/microduck_rl && uv pip install --python .venv-sim/bin/python "
        "pyobjc-framework-Vision pyobjc-framework-Quartz pyobjc-framework-Cocoa\n")
    raise SystemExit(1)

# 直播伴侣可能出现的进程/窗口名（不同版本叫法不同）
APP_KEYS = ("Douyin Webcast Mate", "直播伴侣", "Webcast Mate", "webcastmate")

# 弹幕指令关键词（命中即转发）；喊出鸭子名字的评论一律转发
COMMAND_WORDS = (
    "踢球", "踢个球", "跳舞", "跳个舞", "唱歌", "唱首歌", "跟我", "跟随",
    "过来", "回来", "捡起", "捡一", "搬", "叼", "叫声", "叫一个", "叫一声",
    "握手", "转圈", "坐下", "站起来", "起立", "打个滚", "翻滚", "停下", "别动",
)

_SEEN_CAP = 500          # 去重缓存容量
_NICK_MAX = 12           # 昵称最大长度（超过视为非评论行）
_BASELINE_POLLUTES = 3   # 启动后先静默观察的轮数（不转发存量评论）


def duck_name() -> str:
    cfg = Path(__file__).resolve().parent.parent / "configs" / "duckpet.toml"
    try:
        import tomllib
        with cfg.open("rb") as f:
            return str(tomllib.load(f).get("name", "")).strip()
    except Exception:
        return ""


def list_windows() -> None:
    infos = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
    for w in infos:
        if w.get("kCGWindowLayer", 0) != 0:
            continue
        b = w.get("kCGWindowBounds", {})
        if b.get("Width", 0) < 100 or b.get("Height", 0) < 100:
            continue
        print(f"id={w.get('kCGWindowNumber'):<8} "
              f"owner={w.get('kCGWindowOwnerName', '')!r} "
              f"title={w.get('kCGWindowName', '')!r} "
              f"bounds=({b.get('X')}, {b.get('Y')}, {b.get('Width')}x{b.get('Height')})")


def find_window(app_key: str):
    keys = (app_key,) if app_key else APP_KEYS
    infos = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
    for w in infos:
        if w.get("kCGWindowLayer", 0) != 0:
            continue
        owner = str(w.get("kCGWindowOwnerName", "") or "")
        title = str(w.get("kCGWindowName", "") or "")
        b = w.get("kCGWindowBounds", {})
        if b.get("Width", 0) < 200 or b.get("Height", 0) < 200:
            continue
        if any(k in owner or k in title for k in keys):
            return w
    return None


def capture(win_id: int, region: tuple[float, float, float, float] | None):
    img = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        win_id,
        Quartz.kCGWindowImageBoundsIgnoreFraming | Quartz.kCGWindowImageNominalResolution)
    if img is None or region is None:
        return img
    width = Quartz.CGImageGetWidth(img)
    height = Quartz.CGImageGetHeight(img)
    x, y, w, h = region
    # CGImage 像素坐标原点在左上角，与 region 的约定一致
    crop = Quartz.CGRectMake(x * width, y * height, w * width, h * height)
    return Quartz.CGImageCreateWithImageInRect(img, crop)


def ocr_lines(cgimg) -> list[tuple[float, float, str]]:
    """返回 [(top 比例, left 比例, 文本)]，按从上到下排序。"""
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLanguages_(["zh-Hans", "en"])
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cgimg, {})
    ok, _err = handler.performRequests_error_([req], None)
    if not ok:
        return []
    out = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        box = obs.boundingBox()  # Vision 归一化坐标，原点在左下角
        top = 1.0 - float(box.origin.y) - float(box.size.height)
        out.append((top, float(box.origin.x), str(cand[0].string())))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


_COMMENT_RE = None


def parse_comments(lines: list[str]) -> list[tuple[str, str]]:
    global _COMMENT_RE
    if _COMMENT_RE is None:
        _COMMENT_RE = re.compile(r"^(.{1,%d}?)[：:]\s*(.+)$" % _NICK_MAX)
    comments = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        m = _COMMENT_RE.match(ln)
        if m:
            nick, content = m.group(1).strip(), m.group(2).strip()
            if nick and content:
                comments.append((nick, content))
    return comments


_NORM_RE = re.compile(r"[\s：:，。！!？?,.、~…·\"'“”‘’]+")


def _dedupe_key(nick: str, content: str) -> str:
    # OCR 同一行两次识别常在标点/空白上抖动，去重键先剥掉这些字符
    return hashlib.md5(_NORM_RE.sub("", nick + content).encode("utf-8")).hexdigest()


def looks_like_command(text: str, name: str) -> bool:
    if name and name in text:
        return True
    return any(w in text for w in COMMAND_WORDS)


def main() -> None:
    ap = argparse.ArgumentParser(description="直播伴侣评论区 → DuckPet 指令桥")
    ap.add_argument("--app", default="", help="窗口名匹配关键词（默认自动匹配直播伴侣）")
    ap.add_argument("--region", default="0.56,0.42,0.44,0.48",
                    help="评论区在窗口内的相对位置 x,y,w,h（0~1，左上角原点）。"
                         "默认 0.56,0.42,0.44,0.48（按直播伴侣 1280x720 实测校准："
                         "右侧互动消息区）；布局不同用 --dump 重新校准；填 none=整个窗口")
    ap.add_argument("--interval", type=float, default=2.0, help="轮询间隔秒（默认 2）")
    ap.add_argument("--all", action="store_true", help="转发所有评论（默认只转发像指令的）")
    ap.add_argument("--ignore", action="append", default=[], help="忽略这些昵称（可多次）")
    ap.add_argument("--list", action="store_true", help="列出所有窗口后退出")
    ap.add_argument("--dump", action="store_true", help="OCR 一次并打印每行坐标后退出")
    args = ap.parse_args()

    if args.list:
        list_windows()
        return

    region = None
    if args.region and args.region.lower() != "none":
        vals = [float(v) for v in args.region.split(",")]
        if len(vals) != 4:
            ap.error("--region 需要 4 个数：x,y,w,h（或 none）")
        region = tuple(vals)

    name = duck_name()
    log = lambda *a: print(*a, file=sys.stderr, flush=True)
    log(f"[弹幕桥] 鸭子名字：{name or '（未配置）'}；过滤模式："
        f"{'全部转发' if args.all else '仅指令（含鸭子名字）'}")

    win = None
    while win is None:
        win = find_window(args.app)
        if win is None:
            log("[弹幕桥] 没找到直播伴侣窗口，5 秒后重试（--list 可看所有窗口名）…")
            time.sleep(5)
    b = win["kCGWindowBounds"]
    log(f"[弹幕桥] 锁定窗口 id={win['kCGWindowNumber']} "
        f"{b['Width']:.0f}x{b['Height']:.0f}；区域={region or '整个窗口'}")

    if args.dump:
        img = capture(win["kCGWindowNumber"], region)
        if img is None:
            log("[弹幕桥] 截图失败：请检查屏幕录制权限")
            return
        for top, left, text in ocr_lines(img):
            print(f"({left:.2f}, {top:.2f})  {text}")
        log("[弹幕桥] 左边两列是行在区域内的相对位置 (x, y)，据此设置 --region")
        return

    seen: collections.OrderedDict[str, None] = collections.OrderedDict()
    ignores = set(args.ignore)
    baseline = _BASELINE_POLLUTES
    empty_streak = 0
    while True:
        w = find_window(args.app)
        if w is None:
            log("[弹幕桥] 窗口不见了（直播伴侣关了？），5 秒后重找…")
            seen.clear()
            baseline = _BASELINE_POLLUTES
            time.sleep(5)
            continue
        img = capture(w["kCGWindowNumber"], region)
        lines = [t for _top, _left, t in ocr_lines(img)] if img is not None else []
        if not lines:
            empty_streak += 1
            if empty_streak == 5:
                log("[弹幕桥] 连续多次识别为空：可能没开屏幕录制权限，或评论区不在 --region 里"
                    "（用 --dump 校准）")
        else:
            empty_streak = 0
        for nick, content in parse_comments(lines):
            key = f"{nick}：{content}"
            h = _dedupe_key(nick, content)
            if h in seen:
                continue
            seen[h] = None
            if len(seen) > _SEEN_CAP:
                seen.popitem(last=False)
            if baseline > 0 or nick in ignores:
                continue
            if args.all or looks_like_command(content, name):
                print(key, flush=True)          # ← 这一行进鸭子的 stdin
                log(f"[弹幕桥] 已转发：{key}")
            else:
                log(f"[弹幕桥] 忽略（不像指令）：{key}")
        if baseline > 0:
            baseline -= 1
            if baseline == 0:
                log(f"[弹幕桥] 基线建立完成（已存 {len(seen)} 条存量评论），开始转发新评论")
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
