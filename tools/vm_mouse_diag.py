"""鼠标通道诊断：逐步尝试禁用绝对定位设备，并把每一步结果都写回来。"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import guest_run  # noqa: E402

PS = r"""
$ErrorActionPreference = 'Continue'
$ids = @(
  'HID\VID_0E0F&PID_0003&MI_00\8&367BFB7C&0&0000',
  'HID\VID_0E0F&PID_0003&MI_01\8&12A4BDBA&0&0000'
)
'--- 1. 禁用前 ---'
(Get-PnpDevice -Class Mouse -ErrorAction SilentlyContinue |
  Select-Object Status, FriendlyName, InstanceId |
  Format-Table -AutoSize | Out-String -Width 200)

'--- 2. 逐条禁用 ---'
foreach ($iid in $ids) {
  try {
    Disable-PnpDevice -InstanceId $iid -Confirm:$false -ErrorAction Stop
    'OK  禁用 ' + $iid
  } catch {
    'FAIL 禁用 ' + $iid + ' : ' + $_.Exception.Message
  }
}

Start-Sleep -Seconds 3

'--- 3. 禁用后 ---'
(Get-PnpDevice -Class Mouse -ErrorAction SilentlyContinue |
  Select-Object Status, FriendlyName, InstanceId |
  Format-Table -AutoSize | Out-String -Width 200)

'--- 4. 残留鼠标设备（相对定位） ---'
(Get-PnpDevice -ErrorAction SilentlyContinue |
  Where-Object { $_.Class -eq 'Mouse' -and $_.Status -eq 'OK' } |
  Select-Object FriendlyName, InstanceId |
  Format-Table -AutoSize | Out-String -Width 200)
"""

if __name__ == "__main__":
    out = guest_run(PS, timeout=420)
    (BASE_DIR / "logs" / "mouse_diag.txt").write_text(out, encoding="utf-8")
    print(out)
