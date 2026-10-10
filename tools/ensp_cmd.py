"""直接给 eNSP 主窗口发 WM_COMMAND：探测菜单/工具栏命令 ID。

思路（2026-10-01）
------------------
前台锁定让 SetForegroundWindow 失效、合成鼠标也不通，但 eNSP 是 MFC（Afx:...），
工具栏按钮、菜单命令最终都走 **WM_COMMAND(ID)** 到主窗口。
所以可以盲扫 ID 段，看哪个 ID 让「设备被选中/启动」。

观察指标：
  - 状态栏文字（msctls_statusbar32, hwnd=197350）里的「选中: N」
  - 端口 2000+ 是否开始监听
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import tools.vm_guest as vg  # noqa: E402

MAIN = 262612
STATUS = 197350
VIEW = 197352

CS = r"""
Add-Type -Namespace E -Name M -MemberDefinition @'
[DllImport("user32.dll", CharSet=CharSet.Auto, EntryPoint="SendMessageW")] public static extern System.IntPtr SendMessage(System.IntPtr h, uint m, System.IntPtr w, System.IntPtr l);
[DllImport("user32.dll", CharSet=CharSet.Auto, EntryPoint="SendMessageW")] public static extern System.IntPtr SendMessageStr(System.IntPtr h, uint m, System.IntPtr w, System.Text.StringBuilder l);
[DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern bool PostMessage(System.IntPtr h, uint m, System.IntPtr w, System.IntPtr l);

public static string Cmd(int hwnd, int id) {
  System.IntPtr h = (System.IntPtr)hwnd;
  System.IntPtr r = SendMessage(h, 0x0111, (System.IntPtr)id, System.IntPtr.Zero);
  return "WM_COMMAND id=" + id + " -> " + r.ToInt64();
}
public static string Status(int hwnd, int part) {
  System.IntPtr h = (System.IntPtr)hwnd;
  int len = (int)SendMessage(h, 0x0404, (System.IntPtr)part, System.IntPtr.Zero);  // SB_GETTEXTLENGTHW
  System.Text.StringBuilder sb = new System.Text.StringBuilder(512);
  System.IntPtr r = SendMessageStr(h, 0x0402, (System.IntPtr)part, sb);  // SB_GETTEXTW
  return "part" + part + " len=" + len + " r=" + r.ToInt64() + " [" + sb.ToString() + "]";
}
public static string ClickClient(int hwnd, int x, int y) {
  System.IntPtr h = (System.IntPtr)hwnd;
  System.IntPtr lp = (System.IntPtr)((y << 16) | (x & 0xFFFF));
  SendMessage(h, 0x0200, System.IntPtr.Zero, lp);
  System.Threading.Thread.Sleep(60);
  SendMessage(h, 0x0201, (System.IntPtr)1, lp);
  System.Threading.Thread.Sleep(60);
  SendMessage(h, 0x0202, System.IntPtr.Zero, lp);
  return "click (" + x + "," + y + ")";
}
'@
"""


def _run(tail: str, timeout: int = 240) -> str:
    return vg.guest_run(CS + "\n" + tail, timeout=timeout, interactive=True)


def status_snapshot() -> str:
    return _run(
        "$o=@()\n"
        f"for($i=0;$i -lt 6;$i++){{ $o += [E.M]::Status({STATUS}, $i) }}\n"
        "$o -join \"`n\""
    )


def probe(ids: list[int], wait: float = 0.6) -> str:
    lines = ["$o=@()"]
    for i in ids:
        lines.append(f"[void]([E.M]::Cmd({MAIN}, {i}))")
        lines.append(f"Start-Sleep -Milliseconds {int(wait*1000)}")
        lines.append(f"$o += 'id={i} : ' + [E.M]::Status({STATUS}, 2)")
    lines.append("$o -join \"`n\"")
    return _run("\n".join(lines), timeout=600)


def main(argv: list[str]) -> int:
    op = argv[1] if len(argv) > 1 else "status"
    out = Path(r"D:\anyworkspace\python\Agent-Rag-MCP-startup\logs")
    if op == "status":
        r = status_snapshot()
        (out / "_status.txt").write_text(str(r), encoding="utf-8")
        print(str(r))
    elif op == "probe":
        lo, hi = int(argv[2]), int(argv[3])
        r = probe(list(range(lo, hi + 1)))
        (out / f"_probe_{lo}_{hi}.txt").write_text(str(r), encoding="utf-8")
        print("written", len(str(r)))
    elif op == "cmd":
        ids = [int(x) for x in argv[2:]]
        print(probe(ids, wait=1.0))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
