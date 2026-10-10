"""配置/查询来宾自动登录（重启虚拟机后能自动进入桌面会话，GUI 自动化才可用）。

用法：
    python tools/vm_autologon.py status
    python tools/vm_autologon.py set <用户名> <密码>
    python tools/vm_autologon.py clear
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import guest_run  # noqa: E402

KEY = r"HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"

_STATUS = f"""
$k = '{KEY}'
Get-ItemProperty -Path $k |
  Select-Object AutoAdminLogon, DefaultUserName, DefaultDomainName, DefaultPassword |
  Format-List | Out-String -Width 160
'--- 机器名/域 ---'
$env:COMPUTERNAME
"""


def status() -> str:
    return guest_run(_STATUS, timeout=180)


def set_login(user: str, pwd: str) -> str:
    return guest_run(
        f"$k = '{KEY}'\n"
        f"Set-ItemProperty -Path $k -Name AutoAdminLogon -Value '1' -Type String\n"
        f"Set-ItemProperty -Path $k -Name DefaultUserName -Value '{user}' -Type String\n"
        f"Set-ItemProperty -Path $k -Name DefaultPassword -Value '{pwd}' -Type String\n"
        f"Set-ItemProperty -Path $k -Name DefaultDomainName -Value $env:COMPUTERNAME -Type String\n"
        "Remove-ItemProperty -Path $k -Name AutoLogonCount -ErrorAction SilentlyContinue\n"
        "'已设置自动登录'\n" + _STATUS, timeout=240)


def clear() -> str:
    return guest_run(
        f"$k = '{KEY}'\n"
        "Set-ItemProperty -Path $k -Name AutoAdminLogon -Value '0' -Type String\n"
        "Remove-ItemProperty -Path $k -Name DefaultPassword -ErrorAction SilentlyContinue\n"
        "'已关闭自动登录'\n" + _STATUS, timeout=240)


def main(argv: list[str]) -> int:
    op = argv[1] if len(argv) > 1 else "status"
    if op == "set":
        print(set_login(argv[2], argv[3]))
    elif op == "clear":
        print(clear())
    else:
        print(status())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
