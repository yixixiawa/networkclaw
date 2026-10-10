"""底层热键注入（keybd_event），绕过 .NET SendKeys 的焦点判断。

eNSP 是 Qt + 管理员权限进程，`SendKeys.SendWait` 对它无效（焦点判定被 UIPI 拦）。
这里：UIA 找窗口 → SetForegroundWindow → keybd_event 逐键按下/抬起。

用法:
    python tools/vm_hotkey.py ctrl a
    python tools/vm_hotkey.py ctrl shift a
    python tools/vm_hotkey.py VK 0x0D          # 直接发虚拟键码
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import guest_run_elevated  # noqa: E402

VK = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12,
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45, "f": 0x46,
    "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A, "k": 0x4B, "l": 0x4C,
    "m": 0x4D, "n": 0x4E, "o": 0x4F, "p": 0x50, "q": 0x51, "r": 0x52,
    "s": 0x53, "t": 0x54, "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58,
    "y": 0x59, "z": 0x5A,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "space": 0x20,
    "del": 0x2E, "delete": 0x2E, "back": 0x08, "ins": 0x2D,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
}

# 注意：脚本里**绝不能出现 exit** —— guest_run 把输出落地到文件，
# exit 会终止整个 PowerShell，导致文件不生成、只看到 rc=1。
_PS = r"""
$msg = New-Object System.Collections.ArrayList
try {
  Add-Type -AssemblyName UIAutomationClient
  Add-Type -AssemblyName UIAutomationTypes
  Add-Type -Namespace HK -Name I -MemberDefinition @'
[DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, System.UIntPtr dwExtraInfo);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr hWnd);
[DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern int GetWindowText(System.IntPtr h, System.Text.StringBuilder t, int c);
'@
  $null = $msg.Add('addtype ok')
  $AE = [System.Windows.Automation.AutomationElement]
  $TS = [System.Windows.Automation.TreeScope]
  $kids = $AE::RootElement.FindAll($TS::Children, [System.Windows.Automation.Condition]::TrueCondition)
  $null = $msg.Add('windows=' + $kids.Count)
  $hwnd = [IntPtr]::Zero
  foreach ($k in $kids) {
    $nm = [string]$k.Current.Name
    if ($nm -like ('*' + $TITLE + '*')) {
      $h2 = $k.Current.NativeWindowHandle
      $null = $msg.Add('hit [' + $nm + '] h=' + $h2)
      $hwnd = [IntPtr][int64]$h2
    }
  }
  $null = $msg.Add('hwnd=' + $hwnd.ToInt64())
  if ($hwnd.ToInt64() -eq 0) {
    $null = $msg.Add('ERR: 未找到窗口 ' + $TITLE)
  } else {
    $fgok = [HK.I]::SetForegroundWindow($hwnd)
    Start-Sleep -Milliseconds 400
    $null = $msg.Add('setfg=' + $fgok + ' vks=' + ($VKS -join ','))
    for ($i = 0; $i -lt $N; $i++) {
      [HK.I]::keybd_event([byte][int]$VKS[$i], 0, 0, [System.UIntPtr]::Zero)
      Start-Sleep -Milliseconds 90
    }
    for ($i = $N - 1; $i -ge 0; $i--) {
      [HK.I]::keybd_event([byte][int]$VKS[$i], 0, 2, [System.UIntPtr]::Zero)
      Start-Sleep -Milliseconds 90
    }
    $sb = New-Object System.Text.StringBuilder 512
    $null = [HK.I]::GetWindowText([HK.I]::GetForegroundWindow(), $sb, 512)
    $null = $msg.Add('sent ' + $N + ' keys, fg=' + $sb.ToString())
  }
} catch {
  $null = $msg.Add('EXC: ' + $_.Exception.Message)
}
($msg -join ' | ')
"""


def hotkey(keys: list[str], title: str = "eNSP_Client") -> str:
    vks = []
    for k in keys:
        k = k.lower()
        if k.startswith("0x"):
            vks.append(int(k, 16))
        elif k in VK:
            vks.append(VK[k])
        else:
            raise SystemExit(f"未知按键: {k}")
    head = _PS.replace("$TITLE", f"'{title}'")
    ps = f"$VKS = @({','.join(str(v) for v in vks)}); $N = {len(vks)}\n" + head
    # eNSP 提权（High IL）后，Medium IL 的 keybd_event 会被 UIPI 静默丢弃
    # （实测 Ctrl+A 落到了前台记事本上）——注入必须以 High IL 执行。
    return guest_run_elevated(ps, timeout=240)


def main(argv: list[str]) -> int:
    keys = argv[1:]
    if not keys:
        print(__doc__)
        return 1
    print(hotkey(keys))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
