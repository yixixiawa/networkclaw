"""输入通道彻底诊断：会话状态 / 桌面是否输入桌面 / 各种注入方式是否生效。

结论会决定后续 GUI 自动化走哪条路。
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import guest_run  # noqa: E402

PS = r"""
$ErrorActionPreference = 'Continue'

'=== 1. 会话状态 ==='
(qwinsta 2>&1 | Out-String -Width 160)
'当前进程 SessionId = ' + (Get-Process -Id $PID).SessionId
'UserInteractive = ' + [Environment]::UserInteractive

'=== 2. 桌面 / 窗口站名称 ==='
Add-Type -Namespace DS -Name D -MemberDefinition @'
[DllImport("user32.dll")] public static extern System.IntPtr GetProcessWindowStation();
[DllImport("user32.dll")] public static extern System.IntPtr GetThreadDesktop(uint tid);
[DllImport("user32.dll", SetLastError=true)] public static extern System.IntPtr OpenInputDesktop(uint flags, bool inherit, uint access);
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern bool GetUserObjectInformation(System.IntPtr h, int idx, System.Text.StringBuilder pv, int n, out uint need);
[DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
static string Name(System.IntPtr h) {
  if (h == System.IntPtr.Zero) return "<null>";
  System.Text.StringBuilder sb = new System.Text.StringBuilder(256);
  uint need;
  bool ok = GetUserObjectInformation(h, 2, sb, 512, out need);
  return ok ? sb.ToString() : "<失败 err=" + System.Runtime.InteropServices.Marshal.GetLastWin32Error() + ">";
}
public static string Report() {
  System.IntPtr ws = GetProcessWindowStation();
  System.IntPtr dt = GetThreadDesktop(GetCurrentThreadId());
  System.IntPtr id = OpenInputDesktop(0, false, 0x0001);
  return "winsta=" + Name(ws) + " desktop=" + Name(dt) + " inputDesktop=" + Name(id);
}
'@
[DS.D]::Report()

'=== 3. 各类注入测试 ==='
Add-Type -Namespace IN -Name M -MemberDefinition @'
[StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
[StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx, dy; public uint data, flags, time; public System.IntPtr extra; }
[StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public MOUSEINPUT mi; }
[DllImport("user32.dll", SetLastError=true)] public static extern bool SetCursorPos(int X, int Y);
[DllImport("user32.dll", SetLastError=true)] public static extern bool GetCursorPos(out POINT p);
[DllImport("user32.dll", SetLastError=true)] public static extern uint SendInput(uint n, INPUT[] a, int size);
[DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
public static string SetPos(int x, int y) {
  bool ok = SetCursorPos(x, y);
  int err = System.Runtime.InteropServices.Marshal.GetLastWin32Error();
  POINT p; GetCursorPos(out p);
  return "SetCursorPos=" + ok + " err=" + err + " cursor=" + p.X + "," + p.Y;
}
public static string MoveRel(int dx, int dy) {
  INPUT[] a = new INPUT[1];
  a[0].type = 0; a[0].mi.dx = dx; a[0].mi.dy = dy; a[0].mi.flags = 0x0001;
  uint r = SendInput(1, a, Marshal.SizeOf(typeof(INPUT)));
  int err = System.Runtime.InteropServices.Marshal.GetLastWin32Error();
  System.Threading.Thread.Sleep(200);
  POINT p; GetCursorPos(out p);
  return "SendInput(rel " + dx + "," + dy + ")=" + r + " err=" + err + " cursor=" + p.X + "," + p.Y;
}
'@
[IN.M]::SetPos(300,300)
[IN.M]::SetPos(900,500)
[IN.M]::MoveRel(30, 40)
'屏幕尺寸 = ' + [IN.M]::GetSystemMetrics(0) + 'x' + [IN.M]::GetSystemMetrics(1)
"""

if __name__ == "__main__":
    out = guest_run(PS, timeout=300, interactive=True)
    (BASE_DIR / "logs" / "input_diag.txt").write_text(out, encoding="utf-8")
    print(out)
