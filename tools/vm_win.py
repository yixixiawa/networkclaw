"""来宾窗口操作（枚举 / 激活 / 关闭 / 剪贴板 + 键鼠）。

eNSP 是 Qt 程序，UI Automation 只能看到它的顶层窗口（内部 0 按钮），
因此 eNSP 内部交互走「截图定位 + SetForegroundWindow + 点击 / SendKeys」。

坑：用 Add-Type 声明 EnumWindows 委托回调会让 powershell 进程 0xC0000409 崩溃，
    枚举窗口一律用 UIAutomation 的 RootElement.Children。

用法：
    python tools/vm_win.py list
    python tools/vm_win.py close "<标题包含>"
    python tools/vm_win.py activate "<标题包含>"
    python tools/vm_win.py clip "<文本>"          设置来宾剪贴板
    python tools/vm_win.py keys "<SendKeys 语法>"
    python tools/vm_win.py click <x> <y>
    python tools/vm_win.py screen [宿主输出路径]
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import capture_screen, guest_run, guest_run_elevated  # noqa: E402

_UIA = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$kids = $AE::RootElement.FindAll($TS::Children, [System.Windows.Automation.Condition]::TrueCondition)
"""


def win_list() -> str:
    ps = _UIA + r"""
foreach ($k in $kids) {
  $c = $k.Current
  $r = $c.BoundingRectangle
  "hwnd=$($c.NativeWindowHandle) pid=$($c.ProcessId) cls=$($c.ClassName) name=[$($c.Name)] rect=$([int]$r.X),$([int]$r.Y),$([int]$r.Width)x$([int]$r.Height) ctrl=$($c.ControlType.ProgrammaticName)"
}
"共计 " + $kids.Count + " 个顶层窗口"
"""
    return guest_run(ps, timeout=240, interactive=True)


def _match(title: str, action: str) -> str:
    ps = _UIA + rf"""
$tgt = '{title}'
$hit = 0
foreach ($k in $kids) {{
  $n = $k.Current.Name
  if ($n -like ('*' + $tgt + '*')) {{
    {action}
    $hit++
  }}
}}
'命中 ' + $hit + ' 个窗口（目标: ' + $tgt + '）'
"""
    return guest_run(ps, timeout=240, interactive=True)


def win_close(title: str) -> str:
    action = (
        "try { $wp = $k.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern); "
        "$wp.Close(); 'CLOSE -> ' + $n } catch { 'CLOSE 失败(' + $n + '): ' + $_.Exception.Message }"
    )
    return _match(title, action)


def win_activate(title: str) -> str:
    action = (
        "try { $k.SetFocus(); "
        "$h = [System.IntPtr]$k.Current.NativeWindowHandle; "
        "if ($h -ne [System.IntPtr]::Zero) { "
        "Add-Type -Namespace W -Name U -MemberDefinition @'\n"
        "[DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(System.IntPtr h);\n"
        "[DllImport(\"user32.dll\")] public static extern bool ShowWindow(System.IntPtr h, int n);\n"
        "'@; "
        "[W.U]::ShowWindow($h, 9) | Out-Null; [W.U]::SetForegroundWindow($h) | Out-Null } ; "
        "'ACTIVATE -> ' + $n } catch { 'ACTIVATE 失败(' + $n + '): ' + $_.Exception.Message }"
    )
    return _match(title, action)


def set_clip(text: str) -> str:
    import base64

    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        f"$t = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}')); "
        "[System.Windows.Forms.Clipboard]::SetText($t); "
        "'clip len=' + $t.Length"
    )
    return guest_run(ps, timeout=180, interactive=True)


_MSG = """
[DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
[DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, System.UIntPtr e);
[DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern int GetWindowText(System.IntPtr h, System.Text.StringBuilder t, int c);
"""


def click(x: int, y: int, button: str = "left") -> str:
    flags = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "dbl": (0x0002, 0x0004)}[button]
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -Namespace W2 -Name M -MemberDefinition @'\n" + _MSG + "'@\n"
        f"[W2.M]::SetCursorPos({x}, {y}) | Out-Null\n"
        "Start-Sleep -Milliseconds 250\n"
        f"[W2.M]::mouse_event({hex(flags[0])}, 0, 0, 0, [System.UIntPtr]::Zero)\n"
        "Start-Sleep -Milliseconds 80\n"
        f"[W2.M]::mouse_event({hex(flags[1])}, 0, 0, 0, [System.UIntPtr]::Zero)\n"
        + ("Start-Sleep -Milliseconds 60\n"
           f"[W2.M]::mouse_event({hex(flags[0])}, 0, 0, 0, [System.UIntPtr]::Zero)\n"
           "Start-Sleep -Milliseconds 60\n"
           f"[W2.M]::mouse_event({hex(flags[1])}, 0, 0, 0, [System.UIntPtr]::Zero)\n" if button == "dbl" else "")
        + "$sb3 = New-Object System.Text.StringBuilder 512\n"
        "$null = [W2.M]::GetWindowText([W2.M]::GetForegroundWindow(), $sb3, 512)\n"
        f"\"clicked {x},{y} fg=\" + $sb3.ToString()\n"
    )
    # eNSP 提权运行（High IL）后，Medium IL 的 mouse_event 会被 UIPI 静默丢弃，
    # 表现为「点了没反应」——注入必须以 High IL 执行（见 guest_run_elevated）。
    return guest_run_elevated(ps, timeout=180)


def move(x: int, y: int) -> str:
    """只移动光标（不加点击）：用于验证悬停高亮，从而校对按钮坐标。"""
    ps = (
        "Add-Type -Namespace W3 -Name M -MemberDefinition @'\n" + _MSG + "'@\n"
        f"[W3.M]::SetCursorPos({x}, {y}) | Out-Null\n"
        "Start-Sleep -Milliseconds 400\n"
        f'"[{x},{y}] cursor=" + [System.Windows.Forms.Cursor]::Position'
    )
    return guest_run("Add-Type -AssemblyName System.Windows.Forms; " + ps,
                     timeout=180, interactive=True)


def send_keys(text: str) -> str:
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        f'[System.Windows.Forms.SendKeys]::SendWait("{text}"); '
        f'"sent: {text}"'
    )
    return guest_run(ps, timeout=180, interactive=True)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    op, arg = argv[1], argv[2:]
    if op == "list":
        print(win_list())
    elif op == "close":
        print(win_close(arg[0]))
    elif op == "activate":
        print(win_activate(arg[0]))
    elif op == "clip":
        print(set_clip(arg[0]))
    elif op == "keys":
        print(send_keys(arg[0]))
    elif op == "click":
        print(click(int(arg[0]), int(arg[1]), arg[2] if len(arg) > 2 else "left"))
    elif op == "move":
        print(move(int(arg[0]), int(arg[1])))
    elif op == "screen":
        out = arg[0] if arg else str(BASE_DIR / "logs" / "ensp_screen.png")
        capture_screen(out)
        print(f"screen -> {out}")
    else:
        print(f"未知操作: {op}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
