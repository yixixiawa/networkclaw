"""验证来宾输入注入（UIPI 假设）与提权命令通道是否可用。

实验：
  A. 起一个**非提权**的记事本，SendKeys 打字 → 截图。验证注入在普通窗口是否生效。
  B. 往「管理员: 命令提示符」窗口敲一条写文件命令 → 用 vmrun fileExists 检查落地。
  C. 输出当前 helper 进程的完整性级别 / 是否提权。
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.ensp_ctl import elev_send  # noqa: E402
from tools.vm_guest import capture_screen, exists, guest_run  # noqa: E402
from tools.vm_win import send_keys  # noqa: E402

MARKER = r"C:\elev_probe.txt"


def main() -> None:
    log: list[str] = []

    # C. 自身权限
    log.append("=== C. helper 进程权限 ===")
    log.append(guest_run(
        '$id=[Security.Principal.WindowsIdentity]::GetCurrent(); '
        '"name=" + $id.Name; '
        '"tokenType=" + $id.TokenImpersonationLevel; '
        '$p=New-Object Security.Principal.WindowsPrincipal($id); '
        '"isAdminRole=" + $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator); '
        'try { "elevated=" + ((whoami /groups) -join "`n" -match "S-1-16-12288") } catch { "elevated=?" }'
    ))

    # A. 非提权记事本 + SendKeys
    log.append("=== A. 记事本注⼊测试 ===")
    log.append(guest_run(
        'Get-Process notepad -ErrorAction SilentlyContinue | Stop-Process -Force; '
        'Start-Process notepad; Start-Sleep -Seconds 3; '
        '$p=Get-Process notepad; "notepad pid=" + $p.Id'
    , timeout=180, interactive=True))
    log.append(send_keys("HELLO-UIPI-TEST"))
    capture_screen(str(BASE_DIR / "logs" / "probe_notepad.png"))
    log.append("记事本截图 -> logs/probe_notepad.png")

    # B. 提权窗口通道
    log.append("=== B. 提权 cmd 通道 ===")
    log.append(elev_send(
        f"echo ELEV-OK > {MARKER}",
        f"'ELEV-OK' | Out-File -FilePath {MARKER} -Encoding ascii",
    ))
    log.append(f"vmrun fileExists({MARKER}) = {exists(MARKER)}")
    log.append(guest_run(f'if (Test-Path "{MARKER}") {{ Get-Content "{MARKER}" }} else {{ "marker 不存在" }}'))

    (BASE_DIR / "logs" / "input_probe.txt").write_text("\n".join(log), encoding="utf-8")
    print("\n".join(log))


if __name__ == "__main__":
    main()
