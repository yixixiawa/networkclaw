"""eNSP 实验自动化控制（在虚拟机内操作 eNSP）。

背景与约束：
- eNSP 只装在虚拟机里（C:\\Program Files\\Huawei\\eNSP\\eNSP_Client.exe），
  宿主机没有，因此「打开拓扑 / 启动设备」都必须在来宾内完成；
- GUI 程序必须用 vmrun -interactive 拉起（见 tools/vm_guest.py 的 interactive 参数）；
- vmrun 不回传 stdout，一律通过来宾临时文件 + vm_bridge 回传；
- 传入路径不要经过 bash，避免 Git Bash 把反斜杠转成正斜杠。

子命令：
    list                          列出本地实验与对应来宾拓扑路径
    open <序号|关键词>            用 eNSP 打开该实验的拓扑
    ui                            dump eNSP 主窗口的 UI Automation 树（按钮/菜单名）
    screen [输出路径]             截取来宾屏幕到宿主
    click <x> <y>                 在来宾屏幕上点击
    keys <文本>                   发送按键（SendKeys 语法）
    procs                         列出 eNSP 相关进程与窗口标题
    ports                         检测来宾 2000-2010 的 Telnet 端口开放情况
    stop                          关闭 eNSP 全部相关进程
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import capture_screen, guest_run  # noqa: E402

SRC_DIR = BASE_DIR / "data" / "ensp_labs" / "src"
GUEST_UNZIP = r"C:\Users\yixixiawa\Desktop\unzip"
ENSP_EXE = r"C:\Program Files\Huawei\eNSP\eNSP_Client.exe"
ENS_PWSH = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


# ------------------------------------------------------------------ 实验定位

def labs() -> list[tuple[str, Path]]:
    if not SRC_DIR.is_dir():
        return []
    return [(d.name, d) for d in sorted(SRC_DIR.iterdir()) if d.is_dir()]


def best_topo(lab_dir: Path) -> Path | None:
    """挑一个能解析出设备的 .topo（优先 paper/paper.topo）。"""
    cands = sorted(lab_dir.rglob("*.topo"))
    if not cands:
        return None
    for p in cands:
        if p.name.lower() == "paper.topo":
            return p
    # 退而求其次：体积最大的（通常设备最多）
    return max(cands, key=lambda p: p.stat().st_size)


def guest_path(local: Path) -> str:
    rel = local.relative_to(SRC_DIR)
    return GUEST_UNZIP + "\\" + str(rel)


def resolve(sel: str) -> tuple[str, Path]:
    """按序号或关键词定位实验。"""
    all_labs = labs()
    if sel.isdigit():
        i = int(sel)
        if 1 <= i <= len(all_labs):
            return all_labs[i - 1]
        raise SystemExit(f"序号超范围（1-{len(all_labs)}）")
    for name, d in all_labs:
        if sel in name:
            return name, d
    raise SystemExit(f"未找到匹配「{sel}」的实验")


# ------------------------------------------------------------------ 动作

def _ps_str(s: str) -> str:
    """PowerShell 单引号字符串字面量（内部单引号翻倍转义）。"""
    return "'" + s.replace("'", "''") + "'"


def open_topo(sel: str) -> str:
    name, d = resolve(sel)
    topo = best_topo(d)
    if topo is None:
        raise SystemExit(f"实验「{name}」没有 .topo 文件")
    gp = guest_path(topo)
    # 注意：PowerShell 的转义符是反引号，不是反斜杠；拼接引号要用 '"' + $x + '"'
    script = (
        f"$exe = {_ps_str(ENSP_EXE)}; "
        f"$topo = {_ps_str(gp)}; "
        "'EXE exists: ' + (Test-Path -LiteralPath $exe); "
        "'TOPO exists: ' + (Test-Path -LiteralPath $topo); "
        "Start-Process -FilePath $exe -ArgumentList ('\"' + $topo + '\"'); "
        "Start-Sleep -Seconds 6; "
        "$p = Get-Process eNSP_Client -ErrorAction SilentlyContinue; "
        "if ($p) { 'eNSP_Client PID: ' + ($p.Id -join ',') } else { 'eNSP_Client 未启动' }"
    )
    out = guest_run(script, timeout=300, interactive=True)
    return f"实验：{name}\n拓扑：{gp}\n{out}"


_UI_DUMP_PS = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$AE = [System.Windows.Automation.AutomationElement]
$scope = [System.Windows.Automation.TreeScope]
$p = Get-Process eNSP_Client -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $p) { "eNSP_Client 未运行"; exit }
$cond = New-Object System.Windows.Automation.PropertyCondition($AE::ProcessIdProperty, $p.Id)
$win = $AE::RootElement.FindFirst($scope::Children, $cond)
if (-not $win) { "未找到主窗口"; exit }
"窗口标题: " + $win.Current.Name
"窗口位置: " + $win.Current.BoundingRectangle.Width + "x" + $win.Current.BoundingRectangle.Height
"--- 按钮 ---"
$bc = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
$btns = $win.FindAll($scope::Descendants, $bc)
"按钮数: " + $btns.Count
foreach ($b in $btns) { "  [BTN] " + $b.Current.Name + " @ " + $b.Current.BoundingRectangle.X + "," + $b.Current.BoundingRectangle.Y }
"--- 菜单项 ---"
$mc = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::MenuItem)
$mis = $win.FindAll($scope::Descendants, $mc)
"菜单项数: " + $mis.Count
foreach ($m in $mis) { "  [MI] " + $m.Current.Name }
"""


def ui_dump() -> str:
    return guest_run(_UI_DUMP_PS, timeout=300, interactive=True)


def _mouse_click_ps(x: int, y: int) -> str:
    return rf"""
Add-Type -Namespace W -Name U -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
[DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, System.UIntPtr dwExtraInfo);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr hWnd);
'@
SetCursorPos({x}, {y})
Start-Sleep -Milliseconds 200
[W.U]::mouse_event(0x0002, 0, 0, 0, [System.UIntPtr]::Zero)   # 左键按下
Start-Sleep -Milliseconds 80
[W.U]::mouse_event(0x0004, 0, 0, 0, [System.UIntPtr]::Zero)   # 左键抬起
"clicked {x},{y} cursor=" + [System.Windows.Forms.Cursor]::Position
"""


def click(x: int, y: int) -> str:
    ps = "Add-Type -AssemblyName System.Windows.Forms; " + _mouse_click_ps(x, y)
    return guest_run(ps, timeout=180, interactive=True)


def keys(text: str) -> str:
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        f'[System.Windows.Forms.SendKeys]::SendWait("{text}"); '
        f'"sent: {text}"'
    )
    return guest_run(ps, timeout=180, interactive=True)


def procs() -> str:
    return guest_run(
        'Get-Process | Where-Object {$_.ProcessName -match "eNSP|vbox|qemu|VirtualBox"} | '
        'Select-Object ProcessName,Id,MainWindowTitle | Format-Table -AutoSize | Out-String -Width 200',
        timeout=180,
    )


def ports() -> str:
    ps = (
        '$out=@(); '
        'foreach ($port in 2000..2010) { '
        '  $c = New-Object System.Net.Sockets.TcpClient; '
        '  try { $c.Connect("127.0.0.1", $port); $out += "port $port OPEN" } '
        '  catch { $out += "port $port closed" } '
        '  finally { $c.Close() } }; '
        '$out'
    )
    return guest_run(ps, timeout=180)


_ELEV_PS = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -Namespace W -Name U -MemberDefinition @'
[DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern int GetWindowText(System.IntPtr hWnd, System.Text.StringBuilder text, int count);
'@
# 命令文本以 base64 内嵌，避免引号破坏字符串字面量
$cmd = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__CMD_B64__'))
$psCmd = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__PS_B64__'))
$wsh = New-Object -ComObject WScript.Shell
$focus = ''
$result = 'ABORT: 无可用提权窗口'
foreach ($x in @(
  @{ t = '管理员: 命令提示符'; c = $cmd },
  @{ t = '管理员: Windows PowerShell'; c = $psCmd }
)) {
  $null = $wsh.AppActivate($x.t)
  Start-Sleep -Milliseconds 900
  $h = [W.U]::GetForegroundWindow()
  $sb = New-Object System.Text.StringBuilder 256
  [W.U]::GetWindowText($h, $sb, 256) | Out-Null
  $focus = $sb.ToString()
  "focus: " + $focus
  if ($focus -like ("*" + $x.t + "*")) {
    $wsh.SendKeys($x.c, $true)
    $wsh.SendKeys('{ENTER}', $true)
    $result = 'SENT -> ' + $x.t
    break
  }
}
$result
"""


def elev_send(cmd_text: str, ps_text: str) -> str:
    """把命令敲进虚拟机里**已经提权**的 cmd / PowerShell 窗口。

    背景：eNSP_Client.exe 的清单要求管理员权限，而 vmrun -interactive 拉起的
    进程是非提权令牌，Start-Process 触发 UAC 无人应答 → 自动取消。
    虚拟机桌面上开着「管理员: 命令提示符」与「管理员: Windows PowerShell」，
    分别用 cmd / PowerShell 语法把启动命令敲进去。

    命令文本以 base64 内嵌进 PS 脚本——直接字符串替换会被命令里的引号截断。
    """
    import base64

    def esc(s: str) -> str:
        # SendKeys 特殊字符转义
        return re.sub(r"([+^%~(){}[\]])", r"{\1}", s)

    b64 = lambda s: base64.b64encode(s.encode("utf-8")).decode("ascii")  # noqa: E731
    ps = (_ELEV_PS
          .replace("__CMD_B64__", b64(esc(cmd_text)))
          .replace("__PS_B64__", b64(esc(ps_text))))
    return guest_run(ps, timeout=300, interactive=True)


def stop_ensp() -> str:
    return guest_run(
        'Get-Process eNSP_Client,eNSP_Server,vBoxSVC,vboxheadless -ErrorAction SilentlyContinue | '
        'ForEach-Object { $_.Kill(); "killed " + $_.ProcessName + " " + $_.Id }',
        timeout=180,
    )


# ------------------------------------------------------------------ CLI

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=[
        "list", "open", "openx", "elev", "ui", "screen", "click", "keys", "procs", "ports", "stop"])
    ap.add_argument("arg", nargs="*")
    a = ap.parse_args(argv[1:])

    if a.cmd == "list":
        for i, (name, d) in enumerate(labs(), 1):
            tp = best_topo(d)
            print(f"{i:02d} {name}  ->  {guest_path(tp) if tp else '(无 topo)'}")
    elif a.cmd == "open":
        print(open_topo(a.arg[0]))
    elif a.cmd == "openx":
        # 经虚拟机里已提权的 PowerShell 窗口启动 eNSP（绕开 UAC 无人应答）
        name, d = resolve(a.arg[0])
        topo = best_topo(d)
        if topo is None:
            raise SystemExit(f"实验「{name}」没有 .topo 文件")
        gp = guest_path(topo)
        print(f"实验：{name}\n拓扑：{gp}")
        cmd = f'start "eNSP" "{ENSP_EXE}" "{gp}"'
        ps_cmd = f"& {_ps_str(ENSP_EXE)} {_ps_str(gp)}"
        print(elev_send(cmd, ps_cmd))
    elif a.cmd == "elev":
        # elev "<cmd 语法>" "<ps 语法>"  —— 调试提权窗口通道
        print(elev_send(a.arg[0] if a.arg else "echo elev-test-ok",
                        a.arg[1] if len(a.arg) > 1 else '"elev-test-ok"'))
    elif a.cmd == "ui":
        print(ui_dump())
    elif a.cmd == "screen":
        out = a.arg[0] if a.arg else str(BASE_DIR / "logs" / "ensp_screen.png")
        capture_screen(out)
        print(f"screen -> {out}")
    elif a.cmd == "click":
        print(click(int(a.arg[0]), int(a.arg[1])))
    elif a.cmd == "keys":
        print(keys(a.arg[0]))
    elif a.cmd == "procs":
        print(procs())
    elif a.cmd == "ports":
        print(ports())
    elif a.cmd == "stop":
        print(stop_ensp())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
