"""鼠标通道自检：SetCursorPos / GetCursorPos / SendInput 绝对坐标点击 是否真的生效。

用「点 eNSP 窗口的最小化按钮」做可观测判据——最小化/还原无害且易于恢复。
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import capture_screen, guest_run  # noqa: E402
from tools.vm_win import click  # noqa: E402

_CS = r"""
Add-Type -Namespace P -Name M -MemberDefinition @'
[StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
[StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public System.IntPtr dwExtraInfo; }
[StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public MOUSEINPUT mi; }
[DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
[DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
[DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
[DllImport("user32.dll")] public static extern uint SendInput(uint n, INPUT[] a, int size);
public static string MoveTo(int x, int y) {
  bool ok = SetCursorPos(x, y);
  System.Threading.Thread.Sleep(250);
  POINT p; GetCursorPos(out p);
  return "SetCursorPos(" + x + "," + y + ")=" + ok + " -> GetCursorPos=" + p.X + "," + p.Y;
}
public static string ClickAbs(int x, int y) {
  int sw = GetSystemMetrics(0), sh = GetSystemMetrics(1);
  int ax = (int)(x * 65535.0 / (sw - 1) + 0.5), ay = (int)(y * 65535.0 / (sh - 1) + 0.5);
  INPUT[] a = new INPUT[1];
  a[0].type = 0; a[0].mi.dx = ax; a[0].mi.dy = ay; a[0].mi.dwFlags = 0x0001 | 0x8000 | 0x4000;
  SendInput(1, a, Marshal.SizeOf(typeof(INPUT)));
  System.Threading.Thread.Sleep(150);
  a[0].mi.dwFlags = 0x0002; SendInput(1, a, Marshal.SizeOf(typeof(INPUT)));
  System.Threading.Thread.Sleep(80);
  a[0].mi.dwFlags = 0x0004; SendInput(1, a, Marshal.SizeOf(typeof(INPUT)));
  System.Threading.Thread.Sleep(120);
  POINT p; GetCursorPos(out p);
  return "ClickAbs(" + x + "," + y + ") rel=" + ax + "," + ay + " screen=" + sw + "x" + sh + " cur=" + p.X + "," + p.Y;
}
'@
"""

if __name__ == "__main__":
    log = []
    log.append(guest_run(_CS + " [P.M]::MoveTo(500,300); [P.M]::MoveTo(1642,146); "
                             " [P.M]::ClickAbs(1642,146)", timeout=240, interactive=True))
    capture_screen(str(BASE_DIR / "logs" / "mouse_probe.png"))
    log.append("screen -> logs/mouse_probe.png")
    (BASE_DIR / "logs" / "mouse_probe.txt").write_text("\n".join(log), encoding="utf-8")
    print("\n".join(log))
