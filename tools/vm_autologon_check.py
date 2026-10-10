"""只检查自动登录是否已配好（不打印密码本身）。"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import guest_run  # noqa: E402

PS = r"""
$k = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
$p = Get-ItemProperty -Path $k
'AutoAdminLogon  = ' + $p.AutoAdminLogon
'DefaultUserName = ' + $p.DefaultUserName
'DefaultDomain   = ' + $p.DefaultDomainName
'密码已设置      = ' + ([bool]$p.DefaultPassword)
'密码长度        = ' + ($p.DefaultPassword | ForEach-Object { if ($_) { $_.Length } else { 0 } })
"""

if __name__ == "__main__":
    out = guest_run(PS, timeout=180)
    print(out)
    (BASE_DIR / "logs" / "autologon_check.txt").write_text(out, encoding="utf-8")
