"""来宾键鼠注入（前台窗口 + 真实鼠标事件）。

实测结论（2026-10-01，来宾 192.168.10.130 / Windows Server 2019）
------------------------------------------------------------------
- **键盘注入可用**：`keybd_event` 逐键按下抬起，对普通窗口（记事本）与 eNSP 都送达；
  `SendKeys.SendWait` 依赖焦点判定，对 Qt/管理员程序经常无效，别用。
- **鼠标注入不可用**：这台 VM 的桌面指针被 VMware 输入层钉死在屏幕中心
  （`Cursor.Position` 恒等于 960,540，`SetCursorPos` 返回 False 且 `GetLastError`=0，
  `mouse_event(MOVE)` 也完全不生效；已按会话/SYSTEM 身份双重验证，与注入进程权限无关）。
  连记事本这种普通窗口也点不动 → eNSP 里更是无法点选设备、点绿色「启动设备」按钮。

因此：**凡是不依赖鼠标的自动化一律不要引入鼠标**。eNSP 侧继续走 Ctrl+A 之类键盘路径；
真正需要鼠标的场合，只能靠人工在 VM 窗口里操作（或在宿主端改 VMX/由用户执行）。

用法：
    python tools/vm_kbd.py keys "系统提示符"        # 用 SendKeys 语法
    python tools/vm_kbd.py vk 0x41 0x42            # 直接发虚拟键码
    python tools/vm_kbd.py combo ctrl a            # 组合键
    python tools/vm_kbd.py fg eNSP_Client          # 仅把窗口置前并报告
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import guest_run  # noqa: E402
from tools.vm_hotkey import VK, hotkey  # noqa: E402

_FG_PS = r"""
Add-Type -Namespace FG -Name W -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr h);
[DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int n);
[DllImport("user32.dll")] public static extern bool IsIconic(System.IntPtr h);
[DllImport("user32.dll")] public static extern bool BringWindowToTop(System.IntPtr h);
[DllImport("user32.dll")] public static extern int GetWindowText(System.IntPtr h, System.Text.StringBuilder t, int c);
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(System.IntPtr h, out uint pid);
[DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
[DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
'@
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$AE=[System.Windows.Automation.AutomationElement]
$kids=$AE::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,
  [System.Windows.Automation.Condition]::TrueCondition)
$hwnd=[IntPtr]::Zero
foreach($k in $kids){
  if([string]$k.Current.Name -like ('*' + $TITLE + '*')){ $hwnd=[IntPtr]$k.Current.NativeWindowHandle }
}
if($hwnd.ToInt64() -eq 0){ 'ERR: 未找到窗口 ' + $TITLE } else {
  if([FG.W]::IsIconic($hwnd)){ [FG.W]::ShowWindow($hwnd, 9) | Out-Null; Start-Sleep -Milliseconds 300 }
  # 前台锁定：把自己的线程输入接到当前前台线程上，再 SetForegroundWindow 才会生效
  $fgw = [FG.W]::GetForegroundWindow()
  $pid1 = 0; $pid2 = 0
  $t1 = [FG.W]::GetWindowThreadProcessId($fgw, [ref]$pid1)
  $t2 = [FG.W]::GetWindowThreadProcessId($hwnd, [ref]$pid2)
  $me = [FG.W]::GetCurrentThreadId()
  [FG.W]::AttachThreadInput($me, $t1, $true) | Out-Null
  [FG.W]::AttachThreadInput($me, $t2, $true) | Out-Null
  [FG.W]::BringWindowToTop($hwnd) | Out-Null
  $ok = [FG.W]::SetForegroundWindow($hwnd)
  [FG.W]::AttachThreadInput($me, $t1, $false) | Out-Null
  [FG.W]::AttachThreadInput($me, $t2, $false) | Out-Null
  Start-Sleep -Milliseconds 400
  $sb = New-Object System.Text.StringBuilder 256
  [FG.W]::GetWindowText([FG.W]::GetForegroundWindow(), $sb, 256) | Out-Null
  'setfg=' + $ok + ' fg=[' + $sb.ToString() + ']'
}
"""


def foreground(title: str = "eNSP_Client") -> str:
    """把指定窗口置前，返回实际前台窗口标题（用于确认焦点是否到位）。"""
    return guest_run(_FG_PS.replace("$TITLE", f"'{title}'"), timeout=240, interactive=True)


def send_keys(text: str) -> str:
    return guest_run(
        "Add-Type -AssemblyName System.Windows.Forms; "
        f'[System.Windows.Forms.SendKeys]::SendWait("{text}"); "sent: {text}"',
        timeout=180, interactive=True)


def key_combo(keys: list[str], title: str = "eNSP_Client") -> str:
    """组合键：先把窗口置前（best-effort），再逐键注入。"""
    fg = foreground(title)
    hk = hotkey(keys, title=title)
    return f"{fg} | {hk}"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    op = argv[1]
    if op == "keys":
        print(send_keys(argv[2]))
    elif op == "vk":
        vks = [k if k.startswith("0x") else hex(VK[k.lower()]) for k in argv[2:]]
        print(hotkey(vks))
    elif op == "combo":
        print(key_combo(argv[2:]))
    elif op == "fg":
        print(foreground(argv[2] if len(argv) > 2 else "eNSP_Client"))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
