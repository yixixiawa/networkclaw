"""Win32 控件级操作（枚举子窗口 / 直发鼠标消息 / BM_CLICK）。

为什么需要它：
- 虚拟机开了 VMware 指针集成（vmmouse），来宾里 SetCursorPos 直接返回 False、
  SendInput 绝对坐标也被吞 → 合成鼠标事件整条路走不通；
- 但 eNSP 是 MFC 程序（窗口类 Afx:...），控件都是真 HWND，
  可以直接把 WM_LBUTTONDOWN/UP 发给目标控件，或用 BM_CLICK，绕过鼠标驱动。

子命令：
    tree <hwnd>                 枚举该窗口的所有子窗口（类名/文本/矩形）
    find <hwnd> <类名或文本片段>  找控件
    click <hwnd> <x> <y>        向控件客户区坐标 (x,y) 发鼠标点击消息
    bmclick <hwnd>              发 BM_CLICK（按钮控件）
    menu <hwnd> <id>            发 WM_COMMAND（菜单/工具栏命令 ID）
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import guest_run  # noqa: E402

_CS = r"""
# 注意：MemberDefinition 的内容会被塞进类体，不能出现 using / 顶层语句，
# 因此全部用完全限定名（System.Text.StringBuilder 等）。
Add-Type -Namespace W32 -Name C -MemberDefinition @'
public delegate bool EnumProc(System.IntPtr h, System.IntPtr l);
[StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
[DllImport("user32.dll")] public static extern bool EnumChildWindows(System.IntPtr h, EnumProc cb, System.IntPtr l);
[DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern int GetClassName(System.IntPtr h, System.Text.StringBuilder s, int n);
[DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern int GetWindowText(System.IntPtr h, System.Text.StringBuilder s, int n);
[DllImport("user32.dll")] public static extern bool GetWindowRect(System.IntPtr h, out RECT r);
[DllImport("user32.dll")] public static extern bool IsWindowVisible(System.IntPtr h);
[DllImport("user32.dll")] public static extern System.IntPtr SendMessage(System.IntPtr h, uint m, System.IntPtr w, System.IntPtr l);
[DllImport("user32.dll")] public static extern bool PostMessage(System.IntPtr h, uint m, System.IntPtr w, System.IntPtr l);
[DllImport("user32.dll")] public static extern bool ScreenToClient(System.IntPtr h, ref POINT p);
[StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }

// 把「屏幕坐标的点击」转成客户区坐标后直接投递给窗口。
// 为什么需要：来宾开了 VMware 指针集成（vmmouse），SetCursorPos 返回 False、
// SendInput 也被吞，合成鼠标事件整条路不通；而 eNSP 的工具栏是自绘的，
// 只能靠消息直投。
public static string ClickScreen(System.IntPtr h, int sx, int sy) {
  POINT p = new POINT(); p.X = sx; p.Y = sy;
  ScreenToClient(h, ref p);
  System.IntPtr lp = (System.IntPtr)((p.Y << 16) | (p.X & 0xFFFF));
  SendMessage(h, 0x0200, System.IntPtr.Zero, lp);              // WM_MOUSEMOVE
  System.Threading.Thread.Sleep(80);
  SendMessage(h, 0x0201, (System.IntPtr)1, lp);                // WM_LBUTTONDOWN
  System.Threading.Thread.Sleep(80);
  SendMessage(h, 0x0202, System.IntPtr.Zero, lp);              // WM_LBUTTONUP
  return "sent hwnd=" + h.ToInt64() + " screen=(" + sx + "," + sy
    + ") client=(" + p.X + "," + p.Y + ")";
}

[DllImport("user32.dll")] public static extern bool ClientToScreen(System.IntPtr h, ref POINT p);

public static string ClientOrigin(System.IntPtr h) {
  POINT p = new POINT(); p.X = 0; p.Y = 0;
  ClientToScreen(h, ref p);
  return "hwnd=" + h.ToInt64() + " 客户区原点=(" + p.X + "," + p.Y + ")";
}

public static string Tree(System.IntPtr parent) {
  System.Text.StringBuilder sb = new System.Text.StringBuilder();
  int[] n = new int[] { 0 };
  EnumChildWindows(parent, delegate(System.IntPtr h, System.IntPtr l) {
    if (n[0] > 400) return true;
    System.Text.StringBuilder cls = new System.Text.StringBuilder(128); GetClassName(h, cls, 128);
    System.Text.StringBuilder txt = new System.Text.StringBuilder(256); GetWindowText(h, txt, 256);
    RECT r; GetWindowRect(h, out r);
    sb.AppendLine("hwnd=" + h.ToInt64() + " vis=" + IsWindowVisible(h)
      + " cls=" + cls.ToString() + " text=[" + txt.ToString() + "]"
      + " rect=" + r.Left + "," + r.Top + "," + (r.Right - r.Left) + "x" + (r.Bottom - r.Top));
    n[0]++;
    return true;
  }, System.IntPtr.Zero);
  return sb.ToString();
}

public static string ClickWnd(System.IntPtr h, int x, int y) {
  System.IntPtr lp = (System.IntPtr)((y << 16) | (x & 0xFFFF));
  SendMessage(h, 0x0200, System.IntPtr.Zero, lp);
  SendMessage(h, 0x0201, (System.IntPtr)1, lp);
  System.Threading.Thread.Sleep(60);
  SendMessage(h, 0x0202, System.IntPtr.Zero, lp);
  return "click hwnd=" + h.ToInt64() + " at " + x + "," + y;
}

public static string BmClick(System.IntPtr h) {
  SendMessage(h, 0x00F5, System.IntPtr.Zero, System.IntPtr.Zero);
  return "BM_CLICK -> " + h.ToInt64();
}

public static string WmCommand(System.IntPtr h, int id) {
  int w = (0x0000 << 16) | (id & 0xFFFF);
  SendMessage(h, 0x0111, (System.IntPtr)w, System.IntPtr.Zero);
  return "WM_COMMAND id=" + id + " -> " + h.ToInt64();
}

public static string Info(System.IntPtr h) {
  System.Text.StringBuilder cls = new System.Text.StringBuilder(128); GetClassName(h, cls, 128);
  System.Text.StringBuilder txt = new System.Text.StringBuilder(256); GetWindowText(h, txt, 256);
  RECT r; GetWindowRect(h, out r);
  return "hwnd=" + h.ToInt64() + " cls=" + cls.ToString() + " text=[" + txt.ToString()
    + "] rect=" + r.Left + "," + r.Top + "," + (r.Right - r.Left) + "x" + (r.Bottom - r.Top);
}
'@
"""


def _run(tail: str) -> str:
    return guest_run(_CS + "\n" + tail, timeout=240, interactive=True)


def tree(hwnd: int) -> str:
    return _run(f"$h = [System.IntPtr]{hwnd}\n[W32.C]::Info($h)\n"
                "'--- 子窗口 ---'\n[W32.C]::Tree($h)")


def find(hwnd: int, needle: str) -> str:
    return _run(
        f"$h = [System.IntPtr]{hwnd}\n"
        f"$needle = '{needle}'\n"
        "$all = [W32.C]::Tree($h)\n"
        "($all -split \"`r?`n\") | Where-Object { $_ -like ('*' + $needle + '*') }\n"
        "$hit = (($all -split \"`r?`n\") | Where-Object { $_ -like ('*' + $needle + '*') }).Count\n"
        "'命中 ' + $hit"
    )


def click(hwnd: int, x: int, y: int) -> str:
    return _run(f"[W32.C]::ClickWnd([System.IntPtr]{hwnd}, {x}, {y})")


def clickscreen(hwnd: int, sx: int, sy: int) -> str:
    return _run(f"[W32.C]::ClientOrigin([System.IntPtr]{hwnd})\n"
                f"[W32.C]::ClickScreen([System.IntPtr]{hwnd}, {sx}, {sy})")


def bmclick(hwnd: int) -> str:
    return _run(f"[W32.C]::BmClick([System.IntPtr]{hwnd})")


def menu(hwnd: int, cmd_id: int) -> str:
    return _run(f"[W32.C]::WmCommand([System.IntPtr]{hwnd}, {cmd_id})")


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    op, hwnd, rest = argv[1], int(argv[2]), argv[3:]
    if op == "tree":
        print(tree(hwnd))
    elif op == "find":
        print(find(hwnd, rest[0]))
    elif op == "click":
        print(click(hwnd, int(rest[0]), int(rest[1])))
    elif op == "clickscreen":
        print(clickscreen(hwnd, int(rest[0]), int(rest[1])))
    elif op == "bmclick":
        print(bmclick(hwnd))
    elif op == "menu":
        print(menu(hwnd, int(rest[0])))
    else:
        print(f"未知操作: {op}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
