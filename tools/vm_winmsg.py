"""用 Win32 消息操作窗口（不依赖鼠标驱动）：枚举顶层窗口、最小化、置前。"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import tools.vm_guest as vg  # noqa: E402

CS = r"""
Add-Type -Namespace T -Name W -MemberDefinition @'
public delegate bool EnumProc(System.IntPtr h, System.IntPtr l);
[DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, System.IntPtr l);
[DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern int GetWindowText(System.IntPtr h, System.Text.StringBuilder s, int n);
[DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern int GetClassName(System.IntPtr h, System.Text.StringBuilder s, int n);
[DllImport("user32.dll")] public static extern bool IsWindowVisible(System.IntPtr h);
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(System.IntPtr h, out uint pid);
[DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int cmd);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr h);
[DllImport("user32.dll")] public static extern bool BringWindowToTop(System.IntPtr h);
[DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern bool PostMessage(System.IntPtr h, uint m, System.IntPtr w, System.IntPtr l);
[DllImport("user32.dll")] public static extern System.IntPtr SendMessage(System.IntPtr h, uint m, System.IntPtr w, System.IntPtr l);

public static string List() {
  System.Text.StringBuilder sb = new System.Text.StringBuilder();
  EnumWindows(delegate(System.IntPtr h, System.IntPtr l) {
    if (!IsWindowVisible(h)) return true;
    System.Text.StringBuilder t = new System.Text.StringBuilder(256); GetWindowText(h, t, 256);
    if (t.Length == 0) return true;
    System.Text.StringBuilder c = new System.Text.StringBuilder(256); GetClassName(h, c, 256);
    uint pid = 0; GetWindowThreadProcessId(h, out pid);
    sb.AppendLine(h.ToInt64() + " | pid=" + pid + " | " + c.ToString() + " | " + t.ToString());
    return true;
  }, System.IntPtr.Zero);
  return sb.ToString();
}
public static string Fg() {
  System.IntPtr h = GetForegroundWindow();
  System.Text.StringBuilder t = new System.Text.StringBuilder(256); GetWindowText(h, t, 256);
  return h.ToInt64() + " | " + t.ToString();
}
'@
"""


def _run(tail: str) -> str:
    return vg.guest_run(CS + "\n" + tail, timeout=240, interactive=True)


def main(argv: list[str]) -> int:
    op = argv[1] if len(argv) > 1 else "list"
    out_dir = Path(r"D:\anyworkspace\python\Agent-Rag-MCP-startup\logs")
    if op == "list":
        r = _run("[T.W]::List()\n'--- fg ---'\n[T.W]::Fg()")
        (out_dir / "_topwins.txt").write_text(str(r), encoding="utf-8")
        print("written")
    elif op == "min":
        needle = argv[2]
        tail = (
            f"$needle = '{needle}'\n"
            "[T.W]::List() | Out-Null\n"
            "$found = 0\n"
            "foreach ($ln in ([T.W]::List() -split \"`r?`n\")) {\n"
            "  if ($ln -like ('*' + $needle + '*')) {\n"
            "    $h = [System.IntPtr][int64](($ln -split ' \\| ')[0])\n"
            "    [T.W]::ShowWindow($h, 6) | Out-Null\n"
            "    'min ' + $ln\n"
            "    $found++\n"
            "  }\n"
            "}\n"
            "'-- found ' + $found"
        )
        print(_run(tail))
    elif op == "restore":
        needle = argv[2]
        tail = (
            f"$needle = '{needle}'\n"
            "$found = 0\n"
            "foreach ($ln in ([T.W]::List() -split \"`r?`n\")) {\n"
            "  if ($ln -like ('*' + $needle + '*')) {\n"
            "    $h = [System.IntPtr][int64](($ln -split ' \\| ')[0])\n"
            "    [T.W]::ShowWindow($h, 9) | Out-Null\n"
            "    Start-Sleep -Milliseconds 200\n"
            "    [T.W]::BringWindowToTop($h) | Out-Null\n"
            "    $ok = [T.W]::SetForegroundWindow($h)\n"
            "    'restore ' + $ok + ' ' + $ln\n"
            "    $found++\n"
            "  }\n"
            "}\n"
            "'-- found ' + $found\n"
            "'--- fg ---'\n"
            "[T.W]::Fg()"
        )
        print(_run(tail))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
