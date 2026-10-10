"""探测 vmrun 来宾执行身份：带凭据（yixixiawa）vs 不带凭据（VMware Tools/SYSTEM）。

若不带凭据能以 SYSTEM 运行，则：
  - 可直接改 HKLM 的 UAC 策略（无需提权弹窗）
  - 进程完整性为 High，向提权程序（eNSP）注入键鼠不再被 UIPI 拦

用法: python tools/vm_cred_probe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import guest_run  # noqa: E402

_CHECK = r"""
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
'user=' + $id.Name
'auth=' + $id.AuthenticationType
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
'isAdmin=' + $isAdmin
'--- whoami ---'
(whoami /all 2>&1 | Select-String -Pattern 'Mandatory Level|SeDebugPrivilege|SeTcbPrivilege' | Out-String)
'--- session ---'
'session=' + [System.Diagnostics.Process]::GetCurrentProcess().SessionId
"""

# 完整性级别（SYSTEM / High / Medium），用 token 查询
_IL = r"""
Add-Type -Namespace IL -Name T -MemberDefinition @'
[DllImport("advapi32.dll")] public static extern bool OpenProcessToken(System.IntPtr p, uint a, out System.IntPtr t);
[DllImport("advapi32.dll")] public static extern bool GetTokenInformation(System.IntPtr t, int c, System.IntPtr p, int len, out int ret);
[DllImport("advapi32.dll")] public static extern bool ConvertSidToStringSid(System.IntPtr sid, out System.IntPtr str);
'@
$p = [System.Diagnostics.Process]::GetCurrentProcess().Handle
$t = [IntPtr]::Zero
[IL.T]::OpenProcessToken($p, 0x0008, [ref]$t) | Out-Null
$buf = [Runtime.InteropServices.Marshal]::AllocHGlobal(40)
$ret = 0
[IL.T]::GetTokenInformation($t, 25, $buf, 40, [ref]$ret) | Out-Null
$sid = [Runtime.InteropServices.Marshal]::ReadIntPtr($buf)
$str = [IntPtr]::Zero
[IL.T]::ConvertSidToStringSid($sid, [ref]$str) | Out-Null
$s = [Runtime.InteropServices.Marshal]::PtrToStringAuto($str)
'tokenIL=' + $s
"""


def main() -> int:
    for label, cred in (("带凭据(yixixiawa)", True), ("不带凭据(SYSTEM?)", False)):
        print("=" * 60)
        print(f"### {label}")
        print(guest_run(_CHECK, timeout=240, interactive=True, cred=cred))
        print("-- 完整性 --")
        print(guest_run(_IL, timeout=240, interactive=True, cred=cred))
    return 0


if __name__ == "__main__":
    sys.exit(main())
