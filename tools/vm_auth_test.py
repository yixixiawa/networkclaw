"""测试 vmrun 来宾凭据组合，找出可用的账号密码。"""
from __future__ import annotations

import subprocess
from pathlib import Path

VMRUN = r"D:\vmware\vmrun.exe"
VMX = r"D:\virtualmachine\Windows Server 2019\Windows Server 2019.vmx"

CANDS = [
    ("yixixiawa", "293634Fyx"),
    ("Administrator", "293634Fyx"),
    ("yixixiawa", "eNSP@2026"),
    ("Administrator", "eNSP@2026"),
    ("Administrator", ""),
    ("yixixiawa", ""),
]

out = []
for gu, gp in CANDS:
    args = [VMRUN, "-T", "ws", "-gu", gu]
    if gp:
        args += ["-gp", gp]
    args += ["fileExistsInGuest", VMX, r"C:\Windows\System32\cmd.exe"]
    p = subprocess.run(args, capture_output=True, timeout=120)
    txt = (p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")).strip()
    ok = "does not exist" not in txt.lower() and "Error" not in txt
    out.append(f"[{'OK ' if ok else 'NO '}] {gu!r} / {gp!r} -> {txt[:120]}")

Path("logs").mkdir(exist_ok=True)
Path("logs/vm_auth_test.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
