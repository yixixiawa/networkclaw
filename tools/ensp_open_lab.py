"""在来宾里用 eNSP 打开指定实验拓扑（命令行传参，不依赖文件对话框）。

用法：
    python tools/ensp_open_lab.py <序号|关键词> [--kill]

要点：
- 我们的 vmrun 助手进程本身就是高完整性（管理员令牌），
  所以 Start-Process 拉起 eNSP 不会再触发 UAC 无人应答的问题；
- 先关掉服务器管理器之类的挡路窗口；
- 打开后截图存 logs/ensp_open.png 供核对。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.ensp_ctl import best_topo, guest_path, resolve  # noqa: E402
from tools.vm_guest import capture_screen, guest_run  # noqa: E402

# 需要先关掉的干扰窗口（标题片段）。
# 「eNSP 帮助」：eNSP 启动后几秒内可能弹出「检查虚拟网卡设置」帮助窗口，
# 正好盖在画布/工具栏上——Ctrl+A 全选落空、绿色 ▶ 图标也搜不到，
# 表现为「未找到 green 图标（找到 0 个）」→ 设备一台都起不来（2026-10-01 实测）。
NUISANCE = [
    "服务器管理器", "网络", "Windows PowerShell", "更改密码", "用户账户",
    "eNSP 帮助", "检查虚拟网卡设置",
]


def kill_ensp() -> str:
    return guest_run(
        "Get-Process eNSP_Client,eNSP_Server,eNSP_VBoxServer -ErrorAction SilentlyContinue | "
        "ForEach-Object { try { $_.Kill(); 'killed ' + $_.ProcessName } catch {} }",
        timeout=180)


# 用 Win32 枚举窗口 + PostMessage(WM_CLOSE)，不再用 UIA WindowPattern。
# 旧 UIA 版在每次批量里都「rc=1 + 无输出文件」（logs/batch_*.txt 里 [1] 全是
# <来宾命令未产出输出>），从来没成功过；换成 EnumWindows 直男的方案：
#   - 不依赖 UIA 的 COM 状态，异常也被 try/catch 兜住，保证一定写输出；
#   - WM_CLOSE 对 HTML 帮助窗口（hh.exe 系）同样有效，顺带把 hh.exe 杀掉兜底。
_CLOSE_PS = r"""
$out = @()
try {
  $src = @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class WinList {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  public static List<object[]> Visible() {
    var r = new List<object[]>();
    EnumWindows(delegate(IntPtr h, IntPtr l) {
      if (!IsWindowVisible(h)) return true;
      var sb = new StringBuilder(512);
      GetWindowText(h, sb, 512);
      var t = sb.ToString();
      if (t.Length > 0) r.Add(new object[] { h, t });
      return true;
    }, IntPtr.Zero);
    return r;
  }
}
'@
  if (-not ('WinList' -as [type])) { Add-Type -TypeDefinition $src }
  $targets = @('服务器管理器','网络','Windows PowerShell','更改密码','用户账户','eNSP 帮助','检查虚拟网卡设置')
  foreach ($w in [WinList]::Visible()) {
    $h = $w[0]; $t = [string]$w[1]
    foreach ($f in $targets) {
      if ($t -like ('*' + $f + '*')) {
        [void][WinList]::PostMessage($h, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
        $out += ('closed ' + $t)
        break
      }
    }
  }
} catch { $out += ('ERR ' + $_.Exception.Message) }
try {
  # 服务器管理器（登录自启，WM_CLOSE 对它经常无效，直接杀，且已在注册表关掉自启）；
  # hh.exe = eNSP 的 HTML 帮助窗口宿主；notepad = 排查时残留的记事本。
  Get-Process ServerManager,hh,notepad -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  $out += 'killed ServerManager/hh.exe/notepad'
} catch {}
$out
"""


def close_nuisance() -> str:
    """关掉挡在 eNSP 画布前面的干扰窗口（服务器管理器、eNSP 帮助弹窗等）。"""
    out = guest_run(_CLOSE_PS, timeout=240, interactive=True)
    if "<来宾命令未产出输出>" in out:  # 万一还是没输出，再试一次
        time.sleep(2)
        out = guest_run(_CLOSE_PS, timeout=240, interactive=True)
    return out


# 完整性级别 SID -> 名称
IL_NAME = {
    "S-1-16-12288": "High(管理员)",
    "S-1-16-8192": "Medium(标准用户)",
    "S-1-16-16384": "System",
    "S-1-16-4096": "Low",
    "S-1-16-0": "Untrusted",
}

_IL_PS = r"""
Add-Type -Namespace IL2 -Name T -MemberDefinition @'
[DllImport("advapi32.dll")] public static extern bool OpenProcessToken(System.IntPtr p, uint a, out System.IntPtr t);
[DllImport("advapi32.dll")] public static extern bool GetTokenInformation(System.IntPtr t, int c, System.IntPtr p, int len, out int ret);
[DllImport("advapi32.dll")] public static extern bool ConvertSidToStringSid(System.IntPtr sid, out System.IntPtr str);
'@
if (-not ('IL2.T' -as [type])) { 'addtype failed' } else { }
$proc = Get-Process eNSP_Client -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $proc) { 'eNSP_Client 未运行' } else {
  $t = [IntPtr]::Zero
  $ok = [IL2.T]::OpenProcessToken($proc.Handle, 0x0008, [ref]$t)
  if (-not $ok) { 'OpenProcessToken 失败（目标完整性更高）' } else {
    $buf = [Runtime.InteropServices.Marshal]::AllocHGlobal(40)
    $ret = 0
    [IL2.T]::GetTokenInformation($t, 25, $buf, 40, [ref]$ret) | Out-Null
    $sid = [Runtime.InteropServices.Marshal]::ReadIntPtr($buf)
    $str = [IntPtr]::Zero
    [IL2.T]::ConvertSidToStringSid($sid, [ref]$str) | Out-Null
    [Runtime.InteropServices.Marshal]::PtrToStringAuto($str)
  }
}
"""


def integrity() -> str:
    """查询 eNSP_Client 进程的完整性级别 SID。"""
    sid = guest_run(_IL_PS, timeout=240, interactive=True).strip()
    return f"{sid} [{IL_NAME.get(sid, '?')}]"


def launch(topo_guest: str) -> str:
    """以 **管理员身份** 启动 eNSP（不要降权！）。

    两个环境不一样，别照抄：
    - 在 192.168.10.128 那台机上，vmrun 会话是 **Medium IL**，而 eNSP 是 High IL，
      UIPI 会把注入的键鼠静默丢弃 → 当时必须用 `__COMPAT_LAYER=RunAsInvoker` 降权。
    - 在 192.168.10.130 这台机上实测 vmrun 会话本身就是 **High Mandatory Level**
      （`whoami /groups` 可见 Administrators + High Mandatory Level），
      降权反而有害：**路由器（AR2220）要克隆 AR_Base 并驱动 VirtualBox，
      Medium IL 下初始化失败，eNSP 弹「启动设备 XXX 失败。错误代码：40。初始化失败。」**
      交换机是 eNSP 内部进程模拟，不受影响，于是呈现"只有交换机起来、路由器全挂"的假象。

    所以这里保持 eNSP 的默认提权行为，两边同为 High IL，注入与 VBox 操作都正常。
    """
    script = (
        f"$exe = 'C:\\Program Files\\Huawei\\eNSP\\eNSP_Client.exe'; "
        f"$topo = '{topo_guest}'; "
        "$reg = 'HKCU:\\Software\\Microsoft\\Windows NT\\CurrentVersion\\AppCompatFlags\\Layers'; "
        # UAC 的「管理员提权提示」策略：0 = 不提示、直接提权。
        # 只有它能同时满足两个硬约束，见上面注释里的两难。默认没关时为 5。
        "$uac = (Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
        "Policies\\System' -Name ConsentPromptBehaviorAdmin -ErrorAction SilentlyContinue)"
        ".ConsentPromptBehaviorAdmin; "
        "if ($uac -eq 0) { "
        "  'mode=elevated(UAC off)'; "
        "  Remove-ItemProperty -Path $reg -Name $exe -Force -ErrorAction SilentlyContinue; "
        "  Start-Process -FilePath $exe -ArgumentList ('\"' + $topo + '\"') | Out-Null "
        "} else { "
        "  'mode=RunAsInvoker(UAC on)'; "
        "  $env:__COMPAT_LAYER = 'RunAsInvoker'; "
        "  New-ItemProperty -Path $reg -Name $exe -Value 'RUNASINVOKER' "
        "    -PropertyType String -Force -ErrorAction SilentlyContinue | Out-Null; "
        "  Start-Process -FilePath $exe -ArgumentList ('\"' + $topo + '\"') | Out-Null "
        "}; "
        "Start-Sleep -Seconds 20; "
        "$q = Get-Process eNSP_Client -ErrorAction SilentlyContinue; "
        "if ($q) { 'eNSP_Client PID: ' + ($q.Id -join ',') } else { 'eNSP_Client 未运行' }"
    )
    return guest_run(script, timeout=420, interactive=True)


def main(argv: list[str]) -> int:
    sel = argv[1] if len(argv) > 1 else "01"
    if "--kill" in argv:
        print(kill_ensp())
    name, d = resolve(sel)
    topo = best_topo(d)
    if topo is None:
        raise SystemExit(f"实验「{name}」没有 .topo")
    gp = guest_path(topo)
    print(f"实验：{name}")
    print(f"拓扑：{gp}")
    print(close_nuisance())
    out = launch(gp)
    print(out)
    capture_screen(str(BASE_DIR / "logs" / "ensp_open.png"))
    print("截图 -> logs/ensp_open.png")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
