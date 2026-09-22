#!/usr/bin/env python3
"""直播弹幕 → DuckPet 指令桥（macOS / Windows）。

两种用法：
  1. 嵌入仿真（推荐）：bash tools/sim_duckpet_3d.sh --danmaku
     弹幕监听作为仿真内线程运行，评论和终端键盘输入走同一条队列，
     两路同时生效（这也是 tools/live_danmaku_sim.sh 现在的方式）。
  2. 独立 CLI（校准/调试/自定义管道）：
     python3 tools/live_companion_danmaku.py --list     # 列出所有窗口
     python3 tools/live_companion_danmaku.py --dump     # OCR 一次，打印每行相对坐标
     python3 tools/live_companion_danmaku.py            # 持续监听，评论按「昵称：内容」打印到 stdout

像鸭子指令的评论以「昵称：内容」格式产出，走完整的
身份识别→意图解析→优先级仲裁→执行 管线（观众未登记 = 陌生人，
跟随等特权指令会被礼貌拒绝）。

平台实现（依赖全部懒加载，互不影响）：
  macOS   窗口/截图：Quartz CGWindowList（窗口被遮挡也能截）；
          OCR：Vision 原生中文识别
  Windows 窗口：pywin32 EnumWindows；截图：mss（窗口必须可见，
          不要最小化/遮挡）；OCR：rapidocr_onnxruntime（自带中文模型）
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import re
import sys
import time
from pathlib import Path

# 直播伴侣可能出现的进程/窗口名（不同版本叫法不同）
APP_KEYS = ("Douyin Webcast Mate", "直播伴侣", "Webcast Mate", "webcastmate")

# 弹幕指令关键词（命中即转发）；喊出鸭子名字的评论一律转发
COMMAND_WORDS = (
    "踢球", "踢个球", "跳舞", "跳个舞", "唱歌", "唱首歌", "跟我", "跟随",
    "过来", "回来", "捡起", "捡一", "搬", "叼", "叫声", "叫一个", "叫一声",
    "握手", "转圈", "坐下", "站起来", "起立", "打个滚", "翻滚", "停下", "别动",
)

# 默认评论区在窗口内的相对位置 x,y,w,h（0~1，左上角原点），
# 按直播伴侣 macOS 版 1280x720 实测校准：右侧互动消息区
DEFAULT_REGION = (0.56, 0.42, 0.44, 0.48)

_SEEN_CAP = 500          # 去重缓存容量
_NICK_MAX = 16           # 昵称最大长度（超过视为非评论行）
_BASELINE_POLLUTES = 3   # 启动后先静默观察的轮数（不转发存量评论）
_ROW_Y_TOL = 0.015       # 同一行判定：top 坐标容差（区域高度比例）


def duck_name() -> str:
    cfg = Path(__file__).resolve().parent.parent / "configs" / "duckpet.toml"
    try:
        import tomllib
        with cfg.open("rb") as f:
            return str(tomllib.load(f).get("name", "")).strip()
    except Exception:
        return ""


def parse_region(s: str):
    """'x,y,w,h'（0~1）→ tuple；'none'/空 → None（整个窗口）。"""
    if not s or s.lower() == "none":
        return None
    vals = [float(v) for v in s.split(",")]
    if len(vals) != 4:
        raise ValueError("--region 需要 4 个数：x,y,w,h（或 none）")
    return tuple(vals)


class Win:
    """跨平台窗口句柄：macOS handle=CGWindowID；Windows handle=hwnd。
    rect = 屏幕坐标 (x, y, w, h)。"""

    def __init__(self, handle, title: str, rect: tuple[float, float, float, float]):
        self.handle = handle
        self.title = title
        self.rect = rect

    def __repr__(self) -> str:
        x, y, w, h = self.rect
        return f"Win(id={self.handle} title={self.title!r} rect=({x:.0f},{y:.0f},{w:.0f}x{h:.0f}))"


# ---------------------------------------------------------------- macOS

def _mac_list_windows() -> None:
    import Quartz  # noqa: PLC0415
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


def _mac_find_window(keys: tuple[str, ...]):
    import Quartz  # noqa: PLC0415
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
            return Win(int(w["kCGWindowNumber"]), title or owner,
                       (float(b["X"]), float(b["Y"]),
                        float(b["Width"]), float(b["Height"])))
    return None


def _mac_capture(win: Win, region):
    import Quartz  # noqa: PLC0415
    img = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        win.handle,
        Quartz.kCGWindowImageBoundsIgnoreFraming | Quartz.kCGWindowImageNominalResolution)
    if img is None or region is None:
        return img
    width = Quartz.CGImageGetWidth(img)
    height = Quartz.CGImageGetHeight(img)
    x, y, w, h = region
    # CGImage 像素坐标原点在左上角，与 region 的约定一致
    crop = Quartz.CGRectMake(x * width, y * height, w * width, h * height)
    return Quartz.CGImageCreateWithImageInRect(img, crop)


def _mac_ocr_lines(cgimg) -> list[tuple[float, float, str]]:
    """返回 [(top 比例, left 比例, 文本)]，按从上到下排序。"""
    import Vision  # noqa: PLC0415
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLanguages_(["zh-Hans", "en"])
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(True)
    # options 必须传 None（传 {} 会触发 pyobjc 桥接 bug：
    # NSInvalidArgumentException - key does not exist）
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cgimg, None)
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


# ---------------------------------------------------------------- Windows

_win_ocr_engine = None


def _win_dpi_aware() -> None:
    try:
        import ctypes  # noqa: PLC0415
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _win_list_windows() -> None:
    import win32gui  # noqa: PLC0415

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w, h = right - left, bottom - top
        if w < 100 or h < 100:
            return
        print(f"hwnd={hwnd:<10} class={win32gui.GetClassName(hwnd)!r} "
              f"title={title!r} rect=({left},{top},{w}x{h})")
    win32gui.EnumWindows(cb, None)


def _win_find_window(keys: tuple[str, ...]):
    import win32gui  # noqa: PLC0415
    _win_dpi_aware()
    found: list[Win] = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        cls = win32gui.GetClassName(hwnd) or ""
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w, h = right - left, bottom - top
        if w < 200 or h < 200:
            return
        if any(k in title or k in cls for k in keys):
            found.append(Win(hwnd, title or cls, (float(left), float(top),
                                                 float(w), float(h))))
    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def _win_capture(win: Win, region):
    import mss  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    _win_dpi_aware()
    x, y, w, h = win.rect
    if region is None:
        box = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
    else:
        rx, ry, rw, rh = region
        box = {"left": int(x + rx * w), "top": int(y + ry * h),
               "width": max(1, int(rw * w)), "height": max(1, int(rh * h))}
    with mss.mss() as sct:
        shot = sct.grab(box)
        return np.array(shot)[:, :, :3]  # BGRA → BGR


def _win_ocr_lines(img) -> list[tuple[float, float, str]]:
    global _win_ocr_engine
    if _win_ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
        _win_ocr_engine = RapidOCR()
    result, _elapsed = _win_ocr_engine(img)
    h_px, w_px = img.shape[:2]
    out = []
    for box, text, _score in result or []:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append((min(ys) / h_px, min(xs) / w_px, str(text)))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


# ---------------------------------------------------------------- 平台分发

_MAC_DEPS_HINT = ("cd third_party/microduck_rl && uv pip install "
                  "--python .venv-sim/bin/python pyobjc-framework-Vision "
                  "pyobjc-framework-Quartz pyobjc-framework-Cocoa")
_WIN_DEPS_HINT = ("uv pip install --python "
                  "third_party/microduck_rl/.venv-sim/Scripts/python.exe "
                  "mss pywin32 rapidocr_onnxruntime")


def _missing_deps(platform: str) -> str:
    hint = _MAC_DEPS_HINT if platform == "darwin" else _WIN_DEPS_HINT
    return f"[弹幕桥] 缺少 {platform} 平台 OCR 依赖，请执行：\n  {hint}"


def list_windows() -> None:
    if sys.platform == "darwin":
        _mac_list_windows()
    elif sys.platform == "win32":
        _win_list_windows()
    else:
        print(f"暂不支持的平台：{sys.platform}（可用自定义弹幕源管道接入，见 README）")


def find_window(app_key: str = ""):
    keys = (app_key,) if app_key else APP_KEYS
    if sys.platform == "darwin":
        return _mac_find_window(keys)
    if sys.platform == "win32":
        return _win_find_window(keys)
    return None


def capture(win: Win, region):
    if sys.platform == "darwin":
        return _mac_capture(win, region)
    return _win_capture(win, region)


def ocr_lines(img) -> list[tuple[float, float, str]]:
    if sys.platform == "darwin":
        return _mac_ocr_lines(img)
    return _win_ocr_lines(img)


def deps_ok() -> bool:
    try:
        if sys.platform == "darwin":
            import Quartz  # noqa: PLC0415, F401
            import Vision  # noqa: PLC0415, F401
        elif sys.platform == "win32":
            import mss  # noqa: PLC0415, F401
            import win32gui  # noqa: PLC0415, F401
            import rapidocr_onnxruntime  # noqa: PLC0415, F401
        else:
            return False
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------- 评论解析

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


def rows_from_ocr(items: list[tuple[float, float, str]],
                  y_tol: float = _ROW_Y_TOL) -> list[str]:
    """把 OCR 碎片按行合并：top 相近（容差内）且 left 递增的碎片拼成一行。
    应对昵称和内容被 OCR 识别为同一行两段的情况。"""
    rows: list[list] = []
    for top, left, text in items:
        if rows and abs(rows[-1][0] - top) <= y_tol:
            rows[-1][1].append((left, text))
        else:
            rows.append([top, [(left, text)]])
    lines = []
    for _top, cells in rows:
        cells.sort(key=lambda c: c[0])
        lines.append(" ".join(t for _, t in cells))
    return lines


_NORM_RE = re.compile(r"[\s：:，。！!？?,.、~…·\"'“”‘’]+")


def _dedupe_key(nick: str, content: str) -> str:
    # OCR 同一行两次识别常在标点/空白上抖动，去重键先剥掉这些字符
    return hashlib.md5(_NORM_RE.sub("", nick + content).encode("utf-8")).hexdigest()


def looks_like_command(text: str, name: str) -> bool:
    if name and name in text:
        return True
    return any(w in text for w in COMMAND_WORDS)


# ---------------------------------------------------------------- 监听主循环

def run_monitor(on_comment, *, app_key: str = "", region=DEFAULT_REGION,
                interval: float = 2.0, forward_all: bool = False,
                ignores: tuple[str, ...] = (), log=None, stop=None) -> None:
    """持续监听评论区；每条新评论以「昵称：内容」回调 on_comment。

    on_comment: 回调函数（嵌入仿真时传 queue.put；CLI 时传 print）
    stop:       可选 threading.Event，置位后退出循环
    """
    log = log or (lambda *a: print(*a, file=sys.stderr, flush=True))
    if not deps_ok():
        log(_missing_deps(sys.platform))
        return

    name = duck_name()
    log(f"[弹幕桥] 鸭子名字：{name or '（未配置）'}；过滤模式："
        f"{'全部转发' if forward_all else '仅指令（含鸭子名字）'}；平台={sys.platform}")
    if sys.platform == "win32":
        log("[弹幕桥] Windows 截图按屏幕区域抓取：直播伴侣窗口请勿最小化/遮挡")

    win = None
    while win is None:
        if stop is not None and stop.is_set():
            return
        win = find_window(app_key)
        if win is None:
            log("[弹幕桥] 没找到直播伴侣窗口，5 秒后重试（--list 可看所有窗口名）…")
            time.sleep(5)
    log(f"[弹幕桥] 锁定窗口 {win!r}；区域={region or '整个窗口'}")

    seen: collections.OrderedDict[str, None] = collections.OrderedDict()
    ignore_set = set(ignores)
    baseline = _BASELINE_POLLUTES
    empty_streak = 0
    while True:
        if stop is not None and stop.is_set():
            return
        w = find_window(app_key)
        if w is None:
            log("[弹幕桥] 窗口不见了（直播伴侣关了？），5 秒后重找…")
            seen.clear()
            baseline = _BASELINE_POLLUTES
            time.sleep(5)
            continue
        img = capture(w, region)
        items = ocr_lines(img) if img is not None else []
        lines = rows_from_ocr(items)
        if not lines:
            empty_streak += 1
            if empty_streak == 5:
                log("[弹幕桥] 连续多次识别为空：可能没开屏幕录制权限，或评论区不在"
                    "默认区域里（用 --dump 校准后用 --danmaku-region/--region 指定）")
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
            if baseline > 0 or nick in ignore_set:
                continue
            if forward_all or looks_like_command(content, name):
                on_comment(key)
                log(f"[弹幕桥] 已转发：{key}")
            else:
                log(f"[弹幕桥] 忽略（不像指令）：{key}")
        if baseline > 0:
            baseline -= 1
            if baseline == 0:
                log(f"[弹幕桥] 基线建立完成（已存 {len(seen)} 条存量评论），开始转发新评论")
        time.sleep(interval)


# ---------------------------------------------------------------- CLI

def main() -> None:
    ap = argparse.ArgumentParser(description="直播伴侣评论区 → DuckPet 指令桥")
    ap.add_argument("--app", default="", help="窗口名匹配关键词（默认自动匹配直播伴侣）")
    ap.add_argument("--region", default=",".join(str(v) for v in DEFAULT_REGION),
                    help="评论区在窗口内的相对位置 x,y,w,h（0~1，左上角原点）。"
                         "布局不同用 --dump 重新校准；填 none=整个窗口")
    ap.add_argument("--interval", type=float, default=2.0, help="轮询间隔秒（默认 2）")
    ap.add_argument("--all", action="store_true", help="转发所有评论（默认只转发像指令的）")
    ap.add_argument("--ignore", action="append", default=[], help="忽略这些昵称（可多次）")
    ap.add_argument("--list", action="store_true", help="列出所有窗口后退出")
    ap.add_argument("--dump", action="store_true", help="OCR 一次并打印每行坐标后退出")
    args = ap.parse_args()

    if args.list:
        list_windows()
        return
    if not deps_ok():
        sys.stderr.write(_missing_deps(sys.platform) + "\n")
        raise SystemExit(1)

    region = parse_region(args.region)
    log = lambda *a: print(*a, file=sys.stderr, flush=True)

    if args.dump:
        win = None
        while win is None:
            win = find_window(args.app)
            if win is None:
                log("[弹幕桥] 没找到直播伴侣窗口，5 秒后重试（--list 可看所有窗口名）…")
                time.sleep(5)
        log(f"[弹幕桥] 锁定窗口 {win!r}；区域={region or '整个窗口'}")
        img = capture(win, region)
        if img is None:
            log("[弹幕桥] 截图失败：macOS 请检查屏幕录制权限；Windows 请确保窗口未最小化")
            return
        for top, left, text in ocr_lines(img):
            print(f"({left:.2f}, {top:.2f})  {text}")
        log("[弹幕桥] 左边两列是行在区域内的相对位置 (x, y)，据此设置 --region")
        return

    run_monitor(print, app_key=args.app, region=region, interval=args.interval,
                forward_all=args.all, ignores=tuple(args.ignore))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
