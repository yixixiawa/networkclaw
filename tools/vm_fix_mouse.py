"""试图修复来宾鼠标注入：禁掉 VMware USB 绝对定位设备，保留 PS/2 相对鼠标。

背景：来宾装了 VMware Tools 后，指针集成（vusb 绝对定位）会把光标完全交给
主机控制 —— 来宾里 SetCursorPos 直接返回 False、SendInput 也被丢弃，
任何 GUI 自动化点击都无效。

用法：
    python tools/vm_fix_mouse.py status
    python tools/vm_fix_mouse.py disable     # 禁用 USB 绝对定位设备
    python tools/vm_fix_mouse.py enable      # 还原
    python tools/vm_fix_mouse.py test        # 测试 SetCursorPos 是否生效
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import guest_run  # noqa: E402

USB_IDS = [
    r"HID\VID_0E0F&PID_0003&MI_00\8&367BFB7C&0&0000",   # VMware USB Pointing Device
    r"HID\VID_0E0F&PID_0003&MI_01\8&12A4BDBA&0&0000",   # HID-compliant mouse
]

_STATUS_PS = r"""
Get-PnpDevice -Class Mouse -ErrorAction SilentlyContinue |
  Select-Object Status, FriendlyName, InstanceId |
  Format-Table -AutoSize | Out-String -Width 200
"""

_TEST_CS = r"""
Add-Type -Namespace Q -Name M -MemberDefinition @'
[StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
[DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
[DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
public static string Move(int x, int y) {
  bool ok = SetCursorPos(x, y);
  System.Threading.Thread.Sleep(200);
  POINT p; GetCursorPos(out p);
  return "SetCursorPos(" + x + "," + y + ")=" + ok + " -> cursor=" + p.X + "," + p.Y;
}
'@
"""


def status() -> str:
    return guest_run(_STATUS_PS, timeout=180)


def set_dev(enabled: bool) -> str:
    verb = "Enable-PnpDevice" if enabled else "Disable-PnpDevice"
    lines = [f"$verb -InstanceId '{iid}' -Confirm:$false -ErrorAction Continue" for iid in USB_IDS]
    ps = "\n".join(lines) + "\nStart-Sleep -Seconds 2\n" + _STATUS_PS
    return guest_run(ps, timeout=300)


def test() -> str:
    return guest_run(_TEST_CS + " [Q.M]::Move(600,400); [Q.M]::Move(1200,700)",
                     timeout=240, interactive=True)


def main(argv: list[str]) -> int:
    op = argv[1] if len(argv) > 1 else "status"
    if op == "status":
        print(status())
    elif op == "disable":
        print(set_dev(False))
    elif op == "enable":
        print(set_dev(True))
    elif op == "test":
        print(test())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
