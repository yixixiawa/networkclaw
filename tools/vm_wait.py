"""等待来宾系统启动完成（VMware Tools 可用 + 桌面会话就绪）。

用法：
    python tools/vm_wait.py [超时秒数]
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

VMRUN = r"D:\vmware\vmrun.exe"
VMX = r"D:\virtualmachine\Windows Server 2019\Windows Server 2019.vmx"
GU, GP = "yixixiawa", "eNSP@2026"


def tools_ready() -> bool:
    p = subprocess.run(
        [VMRUN, "-T", "ws", "-gu", GU, "-gp", GP, "fileExistsInGuest", VMX,
         r"C:\Windows\System32\cmd.exe"],
        capture_output=True, timeout=60)
    txt = (p.stdout + p.stderr).decode("utf-8", "replace")
    return "exists" in txt.lower() and "Error" not in txt


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 420
    t0 = time.time()
    print("等待来宾系统就绪 …")
    while time.time() - t0 < limit:
        try:
            if tools_ready():
                print(f"Tools 就绪，用时 {time.time() - t0:.0f}s")
                return 0
        except subprocess.TimeoutExpired:
            pass
        time.sleep(10)
    print(f"超时（{limit}s）仍未就绪")
    return 1


if __name__ == "__main__":
    sys.exit(main())
