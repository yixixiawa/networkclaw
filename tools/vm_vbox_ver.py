"""设置/查询来宾里 VirtualBox 的注册表版本号。

背景：eNSP 1.2.00.510 会检查 VirtualBox 版本；来宾实际装的是 5.1.24，
但注册表曾被改成 6.0.14（为了骗过华三 HCL 安装包的版本检查），
导致 eNSP 报 "VirtualBox version is not supported"。改回真实版本即可。

用法：
    python tools/vm_vbox_ver.py status
    python tools/vm_vbox_ver.py set 5.1.24 5.1.24r117012
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import guest_run  # noqa: E402

KEY = r"HKLM:\SOFTWARE\Oracle\VirtualBox"


def status() -> str:
    return guest_run(
        "& 'C:\\Program Files\\Oracle\\VirtualBox\\VBoxManage.exe' --version\n"
        f"Get-ItemProperty '{KEY}' | Select-Object Version,VersionExt,InstallDir | "
        "Format-List | Out-String -Width 160", timeout=180)


def set_ver(version: str, ext: str) -> str:
    return guest_run(
        f"try {{ Set-ItemProperty -Path '{KEY}' -Name Version -Value '{version}' -Type String; "
        f"Set-ItemProperty -Path '{KEY}' -Name VersionExt -Value '{ext}' -Type String; "
        "'写入成功' } catch { '写入失败: ' + $_.Exception.Message }\n"
        f"Get-ItemProperty '{KEY}' | Select-Object Version,VersionExt | Format-List | Out-String -Width 160",
        timeout=240)


def main(argv: list[str]) -> int:
    op = argv[1] if len(argv) > 1 else "status"
    if op == "set":
        print(set_ver(argv[2], argv[3]))
    else:
        print(status())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
