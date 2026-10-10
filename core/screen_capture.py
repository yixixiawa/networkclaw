"""窗口截图 + OpenCV 预处理：把「看一眼当前拓扑」变成可自动执行的动作。

为什么要它：
    前面几轮已经能做「用户给一张拓扑图 → 本地多模态模型识读」，但每次都要用户手动
    截图、手动附加。而拓扑是随时在变的（eNSP 里插了根线、改了 VLAN），我们希望
    程序启动时能自己看一眼当前拓扑。

怎么抓：
    1. 枚举可见窗口，按关键字（eNSP / VMware / VirtualBox / GNS3 …）挑目标
    2. **PrintWindow(PW_RENDERFULLCONTENT)** 抓窗口位图 —— 窗口被遮挡也能抓到，
       不必把窗口切到前台（不打扰用户正在做的事）
    3. 按「客户区」裁剪，去掉标题栏 / 窗口边框（这些对识图只有干扰）
    4. OpenCV 后处理：去黑边、等比缩放、落盘 PNG、与上次截图做差分
    5. PrintWindow 拿不到内容（DirectX 渲染窗口常见全黑）时，自动降级为
       「窗口置前 + 屏幕区域抓取」

隐私边界（重要）：
    截图**只落在本机** logs/captures/，识读走本地多模态模型（llama-server + mmproj），
    不外传。要在云端模型上用，也是先本地识读成文字再给云端（多模态桥接）。

依赖：opencv-python-headless（图像处理）、pywin32（窗口）、Pillow（降级抓屏）。
"""
from __future__ import annotations

import datetime
import time
from pathlib import Path

from core.paths import BASE_DIR

# 截图落盘目录（本机，不外传）
CAPTURE_DIR = BASE_DIR / "logs" / "captures"

# 目标窗口关键字（小写匹配标题或类名）。顺序即优先级：越靠前越优先。
DEFAULT_TARGETS: tuple[str, ...] = (
    "ensp",
    "gns3",
    "packet tracer",
    "eveng",
    "vmware",
    "virtualbox",
    "virtual box",
    "qemu",
    "hyper-v",
    "拓扑",
    "topology",
)

# 明显不是拓扑窗口的标题（避免抓到聊天窗口里提到 "vmware" 的文本）
EXCLUDE_HINTS: tuple[str, ...] = ("输入体验", "program manager", "设置")

MAX_SIDE = 1600          # 长边上限（识图前还会再压到 1280 编码）
PRINTWINDOW_FULL = 0x00000002   # PW_RENDERFULLCONTENT（Win 8.1+，能抓 DWM 合成内容）
BLACK_TOLERANCE = 0.985   # 单色占比超过该值判定为「全黑/全白」废图
CHANGED_RATIO = 0.002     # 与上次截图的像素差异比例超过它才算「拓扑变了」


# ---------------------------------------------------------------- 平台能力

def available() -> tuple[bool, str]:
    """当前环境能否窗口截图（返回 (可用, 说明)）"""
    import sys

    if sys.platform != "win32":
        return False, f"当前平台为 {sys.platform}，窗口截图仅支持 Windows"
    try:
        import win32gui  # noqa: F401
        import win32ui  # noqa: F401
    except ImportError as e:
        return False, f"缺少 pywin32（{e}）"
    try:
        import cv2  # noqa: F401
    except ImportError as e:
        return False, f"缺少 opencv-python-headless（{e}）"
    return True, "可窗口截图（PrintWindow + OpenCV 预处理）"


def _cv2():
    import cv2

    return cv2


def _numpy():
    import numpy as np

    return np


# ---------------------------------------------------------------- 窗口枚举

def _ensure_dpi_aware() -> None:
    """确保进程是 DPI 感知的（best-effort，重复调用无害）。

    不做这步的话：GetWindowRect / ClientToScreen 返回的是「逻辑坐标」，
    而 ImageGrab.grab(all_screens=True) 按物理像素裁剪 —— 混用会导致抓取区域
    偏移，把别的窗口内容截进来（既有隐私问题也会让模型误读拓扑）。
    Qt6 进程本身已是 per-monitor aware，这里主要照顾独立脚本进程。
    """
    import sys

    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _client_insets(hwnd: int) -> tuple[int, int, int, int]:
    """客户区相对窗口外框的内缩量 (left, top, right, bottom)，逻辑像素"""
    import win32gui

    win = win32gui.GetWindowRect(hwnd)              # (l, t, r, b)
    cl, ct = win32gui.ClientToScreen(hwnd, (0, 0))
    cw, ch = win32gui.GetClientRect(hwnd)[2:]
    left = cl - win[0]
    top = ct - win[1]
    right = win[2] - (cl + cw)
    bottom = win[3] - (ct + ch)
    return max(0, left), max(0, top), max(0, right), max(0, bottom)


def list_windows(keywords: tuple[str, ...] | None = None) -> list[dict]:
    """列出候选窗口；带 matched=True 的是命中关键字的目标窗口。

    返回项：{hwnd, title, cls, width, height, area, matched, hits, insets}
    """
    ok, _ = available()
    if not ok:
        return []
    import win32gui

    keys = tuple(k.lower() for k in (keywords or DEFAULT_TARGETS))
    rows: list[dict] = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        cls = win32gui.GetClassName(hwnd) or ""
        if any(h in title.lower() for h in EXCLUDE_HINTS):
            return
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        w, h = r - l, b - t
        if w < 120 or h < 80:      # 忽略状态栏/浮窗
            return
        blob = f"{title} {cls}".lower()
        hits = [k for k in keys if k in blob]
        rows.append({
            "hwnd": int(hwnd),
            "title": title,
            "cls": cls,
            "width": w,
            "height": h,
            "area": w * h,
            "matched": bool(hits),
            "hits": hits,
            "insets": _client_insets(hwnd),
        })

    win32gui.EnumWindows(_cb, None)
    # 命中的排前面，再按面积从大到小（大面积更像主窗口）
    rows.sort(key=lambda r: (not r["matched"], -r["area"]))
    return rows


def pick_target(keywords: tuple[str, ...] | None = None) -> dict | None:
    """挑选最合适的目标窗口（优先级：关键字顺序 → 窗口面积）"""
    keys = [k.lower() for k in (keywords or DEFAULT_TARGETS)]
    rows = [r for r in list_windows(keywords) if r["matched"]]
    if not rows:
        return None

    def rank(row: dict) -> tuple:
        best = min((keys.index(h) for h in row["hits"]), default=len(keys))
        return (best, -row["area"])

    return min(rows, key=rank)


# ---------------------------------------------------------------- 抓取位图

def print_window(hwnd: int, hdc: int, flags: int = PRINTWINDOW_FULL) -> bool:
    """调用 user32.PrintWindow。

    注意：**pywin32 没有导出 win32gui.PrintWindow**（不同版本里时有时无），
    必须用 ctypes 直接调 user32，且参数要显式声明类型，否则 64 位下句柄会被截断。
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL
    return bool(user32.PrintWindow(wintypes.HWND(hwnd), wintypes.HDC(hdc),
                                   wintypes.UINT(flags)))


def _grab_printwindow(hwnd: int):
    """PrintWindow 抓窗口位图（不打扰用户，窗口被遮挡也能抓）。返回 BGR ndarray 或 None"""
    import win32gui
    import win32ui

    l, t, r, b = win32gui.GetWindowRect(hwnd)
    w, h = r - l, b - t
    if w <= 0 or h <= 0:
        return None

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    try:
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)
        hdc = int(save_dc.GetSafeHdc())
        if not print_window(hwnd, hdc, PRINTWINDOW_FULL):
            if not print_window(hwnd, hdc, 0):
                return None
        info = bmp.GetInfo()
        bits = bmp.GetBitmapBits(True)
        np = _numpy()
        arr = np.frombuffer(bits, dtype=np.uint8)
        if arr.size < info["bmHeight"] * info["bmWidth"] * 4:
            return None
        arr = arr.reshape((info["bmHeight"], info["bmWidth"], 4))
        return _cv2().cvtColor(arr, _cv2().COLOR_BGRA2BGR)
    finally:
        try:
            win32gui.DeleteObject(bmp.GetHandle())
        except Exception:
            pass
        try:
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception:
            pass


def _force_foreground(hwnd: int) -> bool:
    """把窗口强制切到前台。

    直接 SetForegroundWindow 会被 Windows 拒绝（系统不允许后台进程抢焦点），
    经典解法是 AttachThreadInput 把自己的输入队列临时挂到前台线程上「借权限」。
    """
    import ctypes
    import win32process
    import win32api
    import win32con

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    try:
        fg = user32.GetForegroundWindow()
        if fg == hwnd:
            return True
        fg_tid = user32.GetWindowThreadProcessId(fg, None)
        my_tid = kernel32.GetCurrentThreadId()
        tgt_tid = win32process.GetWindowThreadProcessId(hwnd)[0]
        user32.AttachThreadInput(my_tid, fg_tid, True)
        if tgt_tid and tgt_tid != my_tid:
            user32.AttachThreadInput(my_tid, tgt_tid, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if tgt_tid and tgt_tid != my_tid:
            user32.AttachThreadInput(my_tid, tgt_tid, False)
        user32.AttachThreadInput(my_tid, fg_tid, False)
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)   # ALT 释放，避免残留按键
        win32api.keybd_event(win32con.VK_MENU, 0, 2, 0)
        time.sleep(0.05)
        return user32.GetForegroundWindow() == hwnd
    except Exception:
        try:
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        return False


def _grab_screen_region(hwnd: int):
    """降级方案：把窗口强制切到前台，抓屏幕上该矩形区域。

    只有置前成功才抓 —— 否则屏幕上那个矩形是别的窗口（可能是聊天窗等无关内容，
    既有隐私问题也会让模型误读），此时返回 None。
    """
    import win32con
    import win32gui
    from PIL import ImageGrab

    _ensure_dpi_aware()
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.3)
    except Exception:
        pass
    if not _force_foreground(hwnd):
        return None
    time.sleep(0.5)     # 等窗口完成重绘
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    img = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True)
    np = _numpy()
    arr = np.array(img)
    return _cv2().cvtColor(arr, _cv2().COLOR_RGB2BGR) if arr.ndim == 3 else None


# ---------------------------------------------------------------- OpenCV 预处理

def _blank_ratio(img) -> float:
    """最大单色占比（判断全黑/全白废图）"""
    cv2 = _cv2()
    np = _numpy()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hist = cv2.calcHist([gray], [0], None, [32], [0, 256]).ravel()
    return float(hist.max()) / float(gray.size) if gray.size else 1.0


def is_blank(img) -> bool:
    """是否属于「没抓到内容」（全黑/全白）"""
    if img is None or getattr(img, "size", 0) == 0:
        return True
    return _blank_ratio(img) >= BLACK_TOLERANCE


def dark_ratio(img) -> float:
    """接近黑色的像素占比。虚拟机画面是 DirectX 渲染，PrintWindow 对它经常
    只抓到窗口 UI 框架、画面区全黑 —— 用这个指标发现这种情况并降级抓屏。"""
    if img is None or getattr(img, "size", 0) == 0:
        return 1.0
    cv2 = _cv2()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.countNonZero(cv2.threshold(gray, 12, 255, cv2.THRESH_BINARY_INV)[1])) \
        / float(gray.size)


def content_score(img) -> float:
    """图像内容丰富度（Canny 边缘密度），用于在多种抓取结果里择优"""
    if img is None or getattr(img, "size", 0) == 0:
        return -1.0
    cv2 = _cv2()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    return float(cv2.countNonZero(edges)) / float(edges.size)


def crop_client_area(img, insets: tuple[int, int, int, int], window_size: tuple[int, int]):
    """按客户区内缩量裁掉标题栏与边框（位图尺寸可能与窗口逻辑尺寸不同，按比例换算）"""
    if img is None:
        return None
    ih, iw = img.shape[:2]
    ww, wh = window_size
    if ww <= 0 or wh <= 0:
        return img
    sx, sy = iw / ww, ih / wh
    left, top, right, bottom = (int(round(v * s)) for v, s in
                               zip(insets, (sx, sy, sx, sy)))
    if (left + right) >= iw - 8 or (top + bottom) >= ih - 8:
        return img    # 内缩量异常（窗口无装饰/最大化），不裁
    return img[top:ih - bottom, left:iw - right]


def trim_uniform_border(img, tol: int = 40, dark: bool = True):
    """去掉四周的纯色边（PrintWindow 常见黑边）。找不到内容时原样返回"""
    cv2 = _cv2()
    np = _numpy()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mask = (gray < tol) if dark else (gray > 255 - tol)
    content = cv2.bitwise_not(mask).astype(np.uint8) * 255
    if int(content.sum()) == 0:
        return img
    x, y, w, h = cv2.boundingRect(cv2.findNonZero(content))
    if w < 40 or h < 40:
        return img
    pad = 2
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(img.shape[1], x + w + pad), min(img.shape[0], y + h + pad)
    return img[y0:y1, x0:x1]


def refine(img, max_side: int = MAX_SIDE):
    """标准预处理链：去黑边 → 长边缩放。返回处理后的 BGR 图"""
    cv2 = _cv2()
    if img is None or img.size == 0:
        return None
    out = trim_uniform_border(img)
    h, w = out.shape[:2]
    if max(h, w) > max_side:
        scale = max_side / float(max(h, w))
        out = cv2.resize(out, (max(1, int(w * scale)), max(1, int(h * scale))),
                         interpolation=cv2.INTER_AREA)
    return out


def diff_ratio(img_a, img_b) -> float:
    """两张图的像素差异比例（0~1）。用来判断「拓扑有没有变化」，避免重复识图"""
    cv2 = _cv2()
    np = _numpy()
    if img_a is None or img_b is None:
        return 1.0
    h = min(img_a.shape[0], img_b.shape[0])
    w = min(img_a.shape[1], img_b.shape[1])
    if h < 8 or w < 8:
        return 1.0
    a = cv2.resize(img_a[:h, :w], (480, 300), interpolation=cv2.INTER_AREA)
    b = cv2.resize(img_b[:h, :w], (480, 300), interpolation=cv2.INTER_AREA)
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    ga = cv2.GaussianBlur(ga, (5, 5), 0)
    gb = cv2.GaussianBlur(gb, (5, 5), 0)
    delta = cv2.absdiff(ga, gb)
    _, thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)
    return float(np.count_nonzero(thresh)) / float(thresh.size)


# ---------------------------------------------------------------- 落盘与历史

def _stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def save_image(img, tag: str = "topology") -> Path:
    """保存截图（PNG，本机）"""
    cv2 = _cv2()
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = CAPTURE_DIR / f"{tag}_{_stamp()}.png"
    cv2.imwrite(str(path), img)
    return path


def prune_captures(keep: int = 20) -> int:
    """只保留最近 N 张截图（省磁盘），返回删除数量"""
    if not CAPTURE_DIR.exists():
        return 0
    files = sorted(CAPTURE_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for f in files[keep:]:
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def last_capture() -> Path | None:
    """最近一次截图路径"""
    if not CAPTURE_DIR.exists():
        return None
    files = sorted(CAPTURE_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


# ---------------------------------------------------------------- 一步到位

def capture(keyword: str | None = None, save_raw: bool = True) -> dict:
    """抓取目标窗口（或指定关键字的窗口），返回结果字典。

    返回：
        {"ok": bool, "image": Path|None, "raw": Path|None, "window": dict|None,
         "changed": float, "method": str, "message": str, "windows": [...]}
    """
    ok, why = available()
    if not ok:
        return {"ok": False, "image": None, "raw": None, "window": None,
                "method": "", "changed": 1.0, "message": why, "windows": []}

    keys = (keyword,) if keyword else None
    windows = list_windows(keys)
    target = pick_target(keys)
    if target is None:
        titles = [w["title"] for w in windows if w["title"]][:6]
        return {"ok": False, "image": None, "raw": None, "window": None,
                "method": "", "changed": 1.0, "windows": windows,
                "message": ("没找到 eNSP / 虚拟机窗口"
                            + (f"；当前可见窗口：{'、'.join(titles)}" if titles else "（列表为空）")
                            + "。可用关键字参数指定，例如 keyword='VMware'")}

    size = (target["width"], target["height"])
    method = "PrintWindow"
    img = _grab_printwindow(target["hwnd"])
    promoted = False
    if img is None or is_blank(img) or dark_ratio(img) > 0.30:
        # PrintWindow 没抓到内容，或大片区域是黑的（DirectX 渲染的虚拟机画面抓不到）：
        # 降级为「窗口置前 + 屏幕区域抓取」，并在两种结果里选内容更丰富的。
        alt = _grab_screen_region(target["hwnd"])
        if alt is not None and not is_blank(alt):
            if img is None or is_blank(img) or content_score(alt) > content_score(img) * 1.15:
                img = alt
                method = "screen-region(窗口已置前)"
                promoted = True
        if not promoted and img is None:
            img = alt
            method = "screen-region(降级)"
    if img is None or is_blank(img):
        return {"ok": False, "image": None, "raw": None, "window": target,
                "method": method, "changed": 1.0, "windows": windows,
                "message": f"窗口「{target['title']}」抓不到内容（可能是 DirectX 独占渲染，"
                           f"或窗口已最小化）"}

    raw_path = None
    if save_raw:
        raw_path = save_image(img, "topology_raw")

    # 裁客户区（去标题栏）→ OpenCV 去黑边 + 缩放
    cropped = crop_client_area(img, tuple(target["insets"]), size)
    final = refine(cropped if cropped is not None else img)
    if final is None or is_blank(final):
        return {"ok": False, "image": None, "raw": raw_path, "window": target,
                "method": method, "changed": 1.0, "windows": windows,
                "message": f"窗口「{target['title']}」裁剪后无可识别内容"}

    prev = last_capture()
    ratio = 1.0
    if prev is not None:
        try:
            ratio = diff_ratio(_cv2().imread(str(prev)), final)
        except Exception:
            ratio = 1.0

    path = save_image(final, "topology")
    prune_captures()
    h, w = final.shape[:2]
    return {"ok": True, "image": path, "raw": raw_path, "window": target,
            "method": method, "changed": ratio, "windows": windows,
            "size": [w, h],
            "message": (f"已截取窗口「{target['title']}」({target['width']}x{target['height']})，"
                        f"预处理后 {w}x{h}，方式 {method}，与上次差异 {ratio * 100:.2f}%")}


def describe_windows(keyword: str | None = None) -> str:
    """给用户/日志看的窗口清单"""
    keys = (keyword,) if keyword else None
    rows = list_windows(keys)
    if not rows:
        return "（没有可用的窗口）"
    lines = ["候选窗口（★ = 命中拓扑关键字，优先被抓取）："]
    for r in rows[:12]:
        mark = "★" if r["matched"] else " "
        lines.append(f" {mark} {r['width']}x{r['height']}  {r['title'] or r['cls']}"
                     f"  [{r['cls']}]  hwnd={r['hwnd']:#x}")
    return "\n".join(lines)
