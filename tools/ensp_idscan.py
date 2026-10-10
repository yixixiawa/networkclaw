"""扫描 eNSP WM_COMMAND ID：以「端口 2000+ 是否监听」为判据。

策略：
  1. 记录基线端口集合
  2. 逐个发 WM_COMMAND(id)，每次后查端口集合差集
  3. 命中即把该 ID 记为候选（例如「全选」「开启设备」）
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import tools.vm_guest as vg  # noqa: E402

MAIN = 262612

CS = r"""
Add-Type -Namespace E -Name M -MemberDefinition @'
[DllImport("user32.dll", CharSet=CharSet.Auto, EntryPoint="SendMessageW")] public static extern System.IntPtr SendMessage(System.IntPtr h, uint m, System.IntPtr w, System.IntPtr l);
public static int Cmd(int hwnd, int id) {
  System.IntPtr h = (System.IntPtr)hwnd;
  System.IntPtr r = SendMessage(h, 0x0111, (System.IntPtr)id, System.IntPtr.Zero);
  return (int)r.ToInt64();
}
public static int ClickClient(int hwnd, int x, int y) {
  System.IntPtr h = (System.IntPtr)hwnd;
  System.IntPtr lp = (System.IntPtr)((y << 16) | (x & 0xFFFF));
  SendMessage(h, 0x0200, System.IntPtr.Zero, lp);
  System.Threading.Thread.Sleep(60);
  SendMessage(h, 0x0201, (System.IntPtr)1, lp);
  System.Threading.Thread.Sleep(60);
  SendMessage(h, 0x0202, System.IntPtr.Zero, lp);
  return 1;
}
'@
Add-Type -Namespace P -Name Q -MemberDefinition @'
[DllImport("iphlpapi.dll")] public static extern uint GetExtendedTcpTable(System.IntPtr p, ref int sz, bool order, int af, int cls, int res);
'@
function Get-Ports {
  $r = netstat -an | Select-String ':20\d\d\s' | Out-String
  return $r
}
"""


def _run(tail: str, timeout: int = 600) -> str:
    return vg.guest_run(CS + "\n" + tail, timeout=timeout, interactive=True)


def ports_snapshot() -> str:
    return _run("(netstat -an | Select-String ':20[0-1][0-9]\\s') -join \"`n\"", timeout=180)


def scan(lo: int, hi: int, gap_ms: int = 250) -> list[tuple[int, str]]:
    """逐个 ID，把端口快照变化记录下来。"""
    hits: list[tuple[int, str]] = []
    lines = [
        "$base = (netstat -an | Select-String ':20[0-1][0-9]\\s' | Out-String)",
        "$res = @()",
    ]
    for i in range(lo, hi + 1):
        lines.append(f"[void]([E.M]::Cmd({MAIN}, {i}))")
        lines.append(f"Start-Sleep -Milliseconds {gap_ms}")
        lines.append(
            "$now = (netstat -an | Select-String ':20[0-1][0-9]\\s' | Out-String); "
            f"if ($now -ne $base) {{ $res += ('id={i} CHANGED'); $base = $now }}"
        )
    lines.append("$res -join \"`n\"")
    out = _run("\n".join(lines), timeout=900)
    return out  # type: ignore[return-value]


def main(argv: list[str]) -> int:
    op = argv[1] if len(argv) > 1 else "ports"
    out_dir = Path(r"D:\anyworkspace\python\Agent-Rag-MCP-startup\logs")
    if op == "ports":
        r = ports_snapshot()
        print(str(r))
    elif op == "scan":
        lo, hi = int(argv[2]), int(argv[3])
        r = scan(lo, hi)
        (out_dir / f"_scan_{lo}_{hi}.txt").write_text(str(r), encoding="utf-8")
        print(str(r))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
