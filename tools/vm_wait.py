"""等待来宾系统启动完成（VMware Tools 可用 + 桌面会话就绪）。

用法：
    python tools/vm_wait.py [超时秒数]

凭据与 .vmx 路径统一交给 tools/vm_guest（环境变量 / .env 读取 + 运行中 VM 自动发现）：
这里曾经各自写死一份路径与明文口令，VM 目录一搬家、口令一改就全部失效。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools import vm_guest  # noqa: E402


def tools_ready() -> bool:
    try:
        return vm_guest.exists(r"C:\Windows\System32\cmd.exe")
    except Exception:  # noqa: BLE001  来宾未就绪 / 凭据缺失都算「还没好」
        return False


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    t0 = time.time()
    print(f"等待 {vm_guest.VMX} 就绪（最多 {limit}s）…")
    while time.time() - t0 < limit:
        if tools_ready():
            print(f"就绪（{int(time.time() - t0)}s）")
            return 0
        time.sleep(5)
    print("超时：来宾仍未就绪（检查 VMware Tools 与 .env 里的 VM_GP）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
