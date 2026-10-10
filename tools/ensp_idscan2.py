"""扫描 eNSP WM_COMMAND ID（精简版，避免命令行过长）。

判据：发完 ID 后端口 2000+ 是否出现新监听。
用法：python tools/ensp_idscan2.py <lo> <hi> [批大小]
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import tools.vm_guest as vg  # noqa: E402

MAIN = 262612

HEAD = r"""
Add-Type -Namespace E -Name M -MemberDefinition @'
[DllImport("user32.dll", EntryPoint="SendMessageW")] public static extern System.IntPtr SendMessage(System.IntPtr h, uint m, System.IntPtr w, System.IntPtr l);
public static void Cmd(int hwnd, int id) { SendMessage((System.IntPtr)hwnd, 0x0111, (System.IntPtr)id, System.IntPtr.Zero); }
'@
"""


def batch(ids: list[int]) -> str:
    tail = "$o=@(); $b=(netstat -an|Select-String ':20[01][0-9] '|Out-String); "
    for i in ids:
        tail += f"[E.M]::Cmd({MAIN},{i}); "
    tail += ("Start-Sleep -Milliseconds 900; "
             "$n=(netstat -an|Select-String ':20[01][0-9] '|Out-String); "
             "if($n -ne $b){$o+='CHANGED after ids " + f"{ids[0]}..{ids[-1]}" + "'}else{$o+='.'}; "
             "$o -join [char]10")
    return tail


def main(argv: list[str]) -> int:
    lo, hi = int(argv[1]), int(argv[2])
    step = int(argv[3]) if len(argv) > 3 else 4
    all_out = []
    for start in range(lo, hi + 1, step):
        ids = list(range(start, min(start + step, hi + 1)))
        r = vg.guest_run(HEAD + "\n" + batch(ids), timeout=300, interactive=True)
        all_out.append(f"[{start}-{ids[-1]}] {r}")
        print(all_out[-1].strip())
        sys.stdout.flush()
    Path(r"D:\anyworkspace\python\Agent-Rag-MCP-startup\logs\_idscan2.txt").write_text(
        "\n".join(all_out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
