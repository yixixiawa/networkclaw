"""一次性探测虚拟机来宾环境状态（进程 / 窗口 / 注册表 / 已装模拟器）。"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import guest_run, is_running  # noqa: E402

PS = r"""
"=== 当前用户/是否管理员 ==="
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$p = New-Object Security.Principal.WindowsPrincipal($id)
"user: " + $id.Name
"isAdmin: " + $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

"=== 桌面可见窗口（含是否管理员窗口）==="
Add-Type -Namespace W -Name U -MemberDefinition @'
[System.Delegate] public delegate bool EnumWindowsProc(System.IntPtr hWnd, System.IntPtr lParam);
[DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, System.IntPtr lParam);
[DllImport("user32.dll")] public static extern bool IsWindowVisible(System.IntPtr hWnd);
[DllImport("user32.dll")] public static extern int GetWindowText(System.IntPtr hWnd, System.Text.StringBuilder text, int count);
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(System.IntPtr hWnd, out uint pid);
'@
$sb = New-Object System.Text.StringBuilder 512
$cb = {
  param($h, $l)
  if ([W.U]::IsWindowVisible($h)) {
    $null = [W.U]::GetWindowText($h, $sb, 512)
    $t = $sb.ToString()
    if ($t -and $t.Trim().Length -gt 0) { $pid2 = 0; $null = [W.U]::GetWindowThreadProcessId($h, [ref]$pid2); "WIN[$pid2] " + $t }
  }
  return $true
}
$delegate = [W.U+EnumWindowsProc]$cb
$null = [W.U]::EnumWindows($delegate, [System.IntPtr]::Zero)

"=== 进程（eNSP / VirtualBox / 模拟器相关）==="
Get-Process | Where-Object { $_.ProcessName -match 'eNSP|vbox|VBox|qemu|HCL|Wireshark|VirtualBox' } |
  Select-Object ProcessName, Id | Format-Table -AutoSize | Out-String -Width 120

"=== VirtualBox 注册表 ==="
foreach ($k in @('HKLM:\SOFTWARE\Oracle\VirtualBox', 'HKLM:\SOFTWARE\WOW6432Node\Oracle\VirtualBox')) {
  if (Test-Path $k) {
    "--- $k ---"
    Get-ItemProperty -Path $k | Format-List | Out-String -Width 120
  } else { "--- $k 不存在 ---" }
}

"=== UAC 相关策略 ==="
$pol = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
Get-ItemProperty -Path $pol | Select-Object EnableLUA, ConsentPromptBehaviorAdmin,
  PromptOnSecureDesktop, FilterAdministratorToken | Format-List | Out-String -Width 120

"=== 已安装模拟器目录 ==="
foreach ($d in @('C:\Program Files\Huawei\eNSP', 'C:\Program Files (x86)\Huawei\eNSP',
                 'C:\Program Files\H3C\HCL', 'C:\Program Files (x86)\H3C\HCL',
                 'C:\Program Files\Oracle\VirtualBox')) {
  if (Test-Path $d) { "EXISTS: " + $d } else { "missing: " + $d }
}

"=== 桌面 unzip ==="
$p2 = 'C:\Users\yixixiawa\Desktop\unzip'
if (Test-Path $p2) { (Get-ChildItem $p2 -Directory | Measure-Object).Count.ToString() + ' 个实验目录' } else { 'unzip 不存在' }

"=== 监听端口 2000-2010 ==="
$conns = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object { $_.LocalPort -ge 2000 -and $_.LocalPort -le 2010 }
if ($conns) { $conns | Select-Object LocalPort, OwningProcess | Format-Table -AutoSize | Out-String -Width 80 } else { '无' }
"""

if __name__ == "__main__":
    print("=== vmrun list ===")
    print(is_running())
    print(guest_run(PS, timeout=300))
