"""测试 vmrun 来宾凭据组合，找出当前可用的账号密码。

用法：
    python tools/vm_auth_test.py                      # 只测 .env / 环境变量里配置的那组
    python tools/vm_auth_test.py <账号1> <密码1> ...    # 追加候选组合（成对给出）

为什么改成从参数/环境读：这个脚本原来把**真实的账号口令**写在源码里，
一旦仓库外传就是明文泄漏。现在源码不含任何口令，候选由使用者显式提供。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools import vm_guest  # noqa: E402


def _mask(pw: str) -> str:
    return "***" if pw else "(空)"


def main(argv: list[str]) -> int:
    cands: list[tuple[str, str]] = []
    if vm_guest.USER_CRED[1]:
        cands.append(vm_guest.USER_CRED)
    if vm_guest.ADMIN_CRED[1]:
        cands.append(vm_guest.ADMIN_CRED)
    if len(argv) >= 2:
        for i in range(0, len(argv) - 1, 2):
            cands.append((argv[i], argv[i + 1]))
    if not cands:
        print("没有候选凭据：请在 .env 设置 VM_GU/VM_GP，或以参数成对传入账号密码")
        return 2

    out: list[str] = []
    for gu, gp in cands:
        args = [vm_guest.VMRUN, "-T", "ws", "-gu", gu]
        if gp:
            args += ["-gp", gp]
        args += ["fileExistsInGuest", vm_guest.VMX, r"C:\Windows\System32\cmd.exe"]
        try:
            p = subprocess.run(args, capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            out.append(f"[ERR] {gu!r} / {_mask(gp)} -> {type(e).__name__}: {e}")
            continue
        txt = (p.stdout + p.stderr).decode("utf-8", "replace").strip()
        ok = "does not exist" not in txt.lower() and "Error" not in txt
        out.append(f"[{'OK ' if ok else 'NO '}] {gu!r} / {_mask(gp)} -> {txt[:120]}")

    Path(BASE_DIR / "logs").mkdir(exist_ok=True)
    report = "\n".join(out)
    print(report)
    (BASE_DIR / "logs" / "vm_auth_test.txt").write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
