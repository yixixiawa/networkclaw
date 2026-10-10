"""禁/启 VMware Pointing Device（ACPI\\VMW0003 = vmmouse 指针集成），并测光标。

用法：
    python tools/vm_vmmouse_off.py off
    python tools/vm_vmmouse_off.py on
    python tools/vm_vmmouse_off.py status
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import guest_run  # noqa: E402

VMMOUSE = r"ACPI\VMW0003\4&1BD7F811&0"

_TEST = r"""
Add-Type -Namespace Z -Name M -MemberDefinition @'
[StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
[DllImport("user32.dll", SetLastError=true)] public static extern bool SetCursorPos(int X, int Y);
[DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
[DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, System.UIntPtr e);
public static string Probe() {
  bool ok = SetCursorPos(960, 540);
  System.Threading.Thread.Sleep(250);
  POINT p; GetCursorPos(out p);
  return "SetCursorPos(960,540)=" + ok + " cursor=" + p.X + "," + p.Y;
}
'@
[Z.M]::Probe()
"""


def status() -> str:
    return guest_run(
        "Get-PnpDevice -Class Mouse -ErrorAction SilentlyContinue | "
        "Select-Object Status,FriendlyName,InstanceId | Format-Table -AutoSize | "
        "Out-String -Width 200", timeout=180)


def toggle(enable: bool) -> str:
    verb = "Enable-PnpDevice" if enable else "Disable-PnpDevice"
    return guest_run(
        f"try {{ {verb} -InstanceId '{VMMOUSE}' -Confirm:$false -ErrorAction Stop; "
        f"'{verb} OK' }} catch {{ 'FAIL: ' + $_.Exception.Message }}\n"
        "Start-Sleep -Seconds 2\n"
        "Get-PnpDevice -Class Mouse -ErrorAction SilentlyContinue | "
        "Select-Object Status,FriendlyName | Format-Table -AutoSize | Out-String -Width 120\n"
        + _TEST, timeout=300, interactive=True)


def main(argv: list[str]) -> int:
    op = argv[1] if len(argv) > 1 else "status"
    if op == "off":
        print(toggle(False))
    elif op == "on":
        print(toggle(True))
    else:
        print(status())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
