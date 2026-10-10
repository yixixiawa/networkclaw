"""来宾环境体检：VMX 自动发现 / 身份 / IP / eNSP 安装与运行状态 / 实验目录。

换实验环境后第一件事就是跑它。
用法: python tools/vm_env.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import VMX, exists, guest_run, ps  # noqa: E402

CHECK = r"""
'--- identity ---'
whoami
'--- ipv4 ---'
(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' } |
 Select-Object -ExpandProperty IPAddress) -join ', '
'--- ensp install ---'
$e = 'C:\Program Files\Huawei\eNSP\eNSP_Client.exe'
'eNSP_Client.exe=' + (Test-Path -LiteralPath $e)
if (Test-Path -LiteralPath $e) { 'ver=' + (Get-Item $e).VersionInfo.ProductVersion }
'--- vbox ---'
$v = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
'VBoxManage=' + (Test-Path -LiteralPath $v)
try { 'vboxVer=' + (& $v --version 2>&1) } catch {}
try { 'vboxReg=' + (Get-ItemProperty 'HKLM:\SOFTWARE\Oracle\VirtualBox' -ErrorAction Stop).Version } catch { 'vboxReg=<none>' }
'--- desktop labs ---'
foreach ($p in @('C:\Users\yixixiawa\Desktop\unzip','C:\Users\Public\Desktop\unzip')) {
  'dir ' + $p + ' = ' + (Test-Path -LiteralPath $p)
}
'--- ensp procs ---'
(Get-Process -Name 'eNSP_Client','eNSP_Server','eNSP_VBoxServer','VirtualBox' -ErrorAction SilentlyContinue |
 Select-Object Id,ProcessName | Format-Table -AutoSize | Out-String)
'--- listening 2000-2015 ---'
(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
 Where-Object { $_.LocalPort -ge 2000 -and $_.LocalPort -le 2015 } |
 Sort-Object LocalPort | Select-Object LocalPort | Format-Table -AutoSize | Out-String)
"""


def main() -> int:
    print("VMX =", VMX)
    print(guest_run(CHECK, timeout=300, interactive=True))
    print("--- ps ---")
    print(ps())
    return 0


if __name__ == "__main__":
    sys.exit(main())
