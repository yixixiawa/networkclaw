"""以 SYSTEM 身份在来宾里执行命令（用于 UAC 开启时的特权操作）。

问题背景
--------
UAC 开启（ConsentPromptBehaviorAdmin=5）时，vmrun 的来宾脚本进程虽然显示
「Administrators + High Mandatory Level」，实际拿到的是 **Medium 令牌**：
    - Set-ItemProperty HKLM / New-Item HKLM  → 拒绝访问
    - Disable-PnpDevice / Enable-PnpDevice   → 常规故障
    - 计划任务的 Register/Start               → 拒绝访问 0x80070005
而 `vmrun runProgramInGuest`（带 -gu/-gp、**不带** -interactive）可以塞进
「管理员组用户」，于是我们借它注册一个以 SYSTEM 运行的**计划任务**来干活。

vmrun 的两个硬约束（实测）
-------------------------
1. 带 `-interactive` 时，vmrun 要求凭据账号与当前交互登录用户一致，
   否则报「指定的客户机用户与当前以交互方式登录的用户不匹配」；
   所以特权通道一律不带 -interactive。
2. 不带 `-gu/-gp`（cred=False）时 vmrun 直接报「需要有效用户名和密码」，
   所以特权通道必须带 Administrator 凭据。

用法
----
    python tools/vm_sys.py run "<PowerShell 片段>"
    python tools/vm_sys.py probe          # 打印身份与 UAC 策略
    python tools/vm_sys.py disable-mouse  # 禁用来宾指针设备（VMware vmmouse 重置光标）
    python tools/vm_sys.py enable-mouse
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import tools.vm_guest as vg  # noqa: E402
from tools.vm_guest import (  # noqa: E402
    ADMIN_CRED, VMX, _encode_ps, _vmrun, use_admin,
)

TASK = "NetworkClawSysTask"


def run_as_system(body: str, timeout: int = 600) -> str:
    """以 SYSTEM 身份执行 PowerShell 片段，返回输出。

    关键坑（实测 2026-10-01）：
    - 计划任务参数经 cmd.exe 中转时，**不能用 -EncodedCommand**：cmd 的命令行是
      ASCII/OEM，UTF-16 的 base64 会被按字节拆开 → 脚本变成乱码
      「桷慯業 : 无法将"桷慯業"项识别为 cmdlet」。改装 -Command + 内联脚本（中文安全，
      输出用 [IO.File]::WriteAllText 以 UTF-8 落盘）。
    - 输出不落盘就没法取回（vmrun 不回传来宾 stdout）。
    """
    ps = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    out_guest = rf"C:\Windows\Temp\nc_sys_{uuid.uuid4().hex[:8]}.txt"
    inner = (
        "$ProgressPreference='SilentlyContinue'; "
        f"[IO.File]::WriteAllText('{out_guest}', [string](& {{ {body} }}), "
        "[Text.UTF8Encoding]::new($false))"
    )
    # 内层脚本整体作为 cmd /c 的一个参数：here-string 承载，避免引号/中文被拆
    cmd = f'"{ps}" -NoProfile -NonInteractive -Command "{inner}"'
    runner = (
        f"$name='{TASK}'; "
        f"try {{ Unregister-ScheduledTask -TaskName $name -Confirm:$false "
        f"-ErrorAction SilentlyContinue }} catch {{}}; "
        "$cmd = @'\n" + cmd + "\n'@; "
        "$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c \"' + $cmd + '\"'); "
        f"Register-ScheduledTask -TaskName $name -Action $a "
        f"-Principal (New-ScheduledTaskPrincipal -UserId 'SYSTEM' "
        f"-LogonType ServiceAccount -RunLevel Highest) -Force | Out-Null; "
        "Start-ScheduledTask -TaskName $name; "
        "$i=0; "
        f"while ($i -lt {max(1, timeout * 2)}) {{ "
        "  $st = (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue).State; "
        "  if ($st -eq 'Running') { Start-Sleep -Milliseconds 500; $i++ } else { break } }; "
        "Start-Sleep -Milliseconds 400; "
        f"$r = if (Test-Path '{out_guest}') {{ Get-Content '{out_guest}' -Raw }} "
        "else { '<无输出>' }; "
        f"try {{ Unregister-ScheduledTask -TaskName $name -Confirm:$false "
        f"-ErrorAction SilentlyContinue }} catch {{}}; "
        "$r"
    )

    old = (vg.GU, vg.GP)
    vg.GU, vg.GP = ADMIN_CRED
    use_admin(True)
    try:
        return vg.guest_run(runner, timeout=timeout + 120, cred=True)
    finally:
        vg.GU, vg.GP = old


MOUSE_FILTER = "FriendlyName -match 'Pointing Device|USB Pointing'"


def _mouse(op: str, timeout: int = 600) -> str:
    """逐个设备执行 Disable/Enable。

    必须**一台一跑**：实测把 4 个设备放进同一个 for 循环时，最后那个失败的设备
    （ACPI\\VMW0003 报"不支持"）会让整个脚本的输出落空（返回 <无输出>），
    前面的成功结果也一起丢。
    """
    ids = [
        r"HID\VID_0E0F&PID_0003&MI_00\8&217CCB29&0&0000",
        r"HID\VID_0E0F&PID_0003&MI_01\8&34ACE767&0&0000",
        r"ACPI\VMW0003\4&1BD7F811&0",
    ]
    lines = []
    for i in ids:
        body = (f"try {{ {op}-PnpDevice -InstanceId '{i}' -Confirm:$false "
                f"-ErrorAction Stop; 'OK' }} catch {{ 'FAIL: ' + $_.Exception.Message }}")
        lines.append(f"{op} {i} -> {run_as_system(body, timeout=timeout).strip()}")
    return "\n".join(lines)


def mouse_off(timeout: int = 600) -> str:
    """禁用来宾侧所有 VMware 指针设备（vmmouse）。

    为什么必须禁用：VMware 的 vmmouse 驱动会以极高频率把光标**吸回屏幕中心**
    （实测 Cursor.Position 永远 = 960,540，SetCursorPos 返回「拒绝访问」的 False），
    任何注入的鼠标轨迹都被抹掉，eNSP 里就选不中设备、点不动按钮。
    键盘在此之前一直是好的（所以表现为"能发键、点不动鼠标"）。
    """
    return _mouse("Disable", timeout)


def mouse_on(timeout: int = 600) -> str:
    return _mouse("Enable", timeout)


_PROBE = """
$o = @()
$o += 'whoami: ' + (whoami)
$o += 'HKLM 可写: ' + (try { New-Item 'HKLM:\\SOFTWARE\\NCProbe' -Force -ErrorAction Stop |
        Out-Null; Remove-Item 'HKLM:\\SOFTWARE\\NCProbe' -Force; 'YES' }
        catch { 'NO (' + $_.Exception.Message + ')' })
$p = 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System'
$o += 'UAC: ' + ((Get-ItemProperty $p | Select-Object ConsentPromptBehaviorAdmin,
        PromptOnSecureDesktop, EnableLUA | Format-List | Out-String).Trim())
($o -join "`n")
"""


def main(argv: list[str]) -> int:
    op = argv[1] if len(argv) > 1 else "probe"
    if op == "run":
        print(run_as_system(argv[2]))
    elif op == "probe":
        print("--- 当前（yixixiawa）身份 ---")
        print(vg.guest_run(
            "whoami; 'Mandatory: ' + (whoami /groups | Select-String 'Mandatory')",
            timeout=240))
        print("--- SYSTEM 通道身份 ---")
        print(run_as_system(_PROBE))
    elif op == "disable-mouse":
        print(mouse_off())
    elif op == "enable-mouse":
        print(mouse_on())
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
