"""基于 UI Automation 的控件查找/点击（现在鼠标可控，可直接点到控件中心）。

eNSP 本体是 MFC 自绘，UIA 看不到内部控件；但**标准 Win32 对话框**
（消息框、文件对话框、控制面板等）UIA 完全可见，用这个工具最稳。

用法：
    python tools/vm_uia.py list                        列出顶层窗口
    python tools/vm_uia.py find <名称片段>              在所有窗口里找控件
    python tools/vm_uia.py click <名称片段> [序号]      点击第 N 个匹配控件中心
    python tools/vm_uia.py invoke <名称片段>            用 InvokePattern 触发
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import guest_run  # noqa: E402

_UIA_HEAD = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
"""

_SCAN = r"""
$found = @()
foreach ($w in $AE::RootElement.FindAll($TS::Children, [System.Windows.Automation.Condition]::TrueCondition)) {
  $wn = $w.Current.Name
  $items = $w.FindAll($TS::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
  foreach ($it in $items) {
    try {
      $c = $it.Current
      if ($c.Name -like ('*' + $needle + '*')) {
        $r = $c.BoundingRectangle
        $found += [pscustomobject]@{
          Win = $wn
          Name = $c.Name
          Ctrl = $c.ControlType.ProgrammaticName
          Rect = "$([int]$r.X),$([int]$r.Y),$([int]$r.Width),$([int]$r.Height)"
          El = $it
        }
      }
    } catch {}
  }
}
"""


def find(needle: str) -> str:
    ps = _UIA_HEAD + f"$needle = '{needle}'\n" + _SCAN + r"""
'匹配 ' + $found.Count + ' 个'
foreach ($f in $found) { '  [' + $f.Ctrl + '] win=' + $f.Win + ' name=[' + $f.Name + '] rect=' + $f.Rect }
"""
    return guest_run(ps, timeout=300, interactive=True)


def click_action(needle: str, index: int = 1, mode: str = "click") -> str:
    return _click_action(needle, index, mode)


def _click_action(needle: str, index: int, mode: str) -> str:
    act = {
        "click": (
            # 现鼠标可控：先 SetCursorPos 到控件中心，再真实点击
            "$r = $f.El.Current.BoundingRectangle; "
            "$cx = [int]($r.X + $r.Width / 2); $cy = [int]($r.Y + $r.Height / 2); "
            "[WN.M]::SetCursorPos($cx, $cy) | Out-Null; Start-Sleep -Milliseconds 200; "
            "[WN.M]::mouse_event(0x0002,0,0,0,[System.UIntPtr]::Zero); Start-Sleep -Milliseconds 70; "
            "[WN.M]::mouse_event(0x0004,0,0,0,[System.UIntPtr]::Zero); "
            "'clicked ' + $f.Name + ' @ ' + $cx + ',' + $cy"
        ),
        "invoke": (
            "$p = $f.El.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern); "
            "$p.Invoke(); 'invoked ' + $f.Name"
        ),
    }[mode]
    ps = (
        _UIA_HEAD
        + "Add-Type -Namespace WN -Name M -MemberDefinition @'\n"
        + '[DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);\n'
        + '[DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, System.UIntPtr e);\n'
        + "'@\n"
        + f"$needle = '{needle}'\n" + _SCAN
        + f"$f = $found | Where-Object {{ $_.Rect -ne '' }} | Select-Object -Skip {index - 1} -First 1\n"
        # 注意：不能在这里 exit —— 包装脚本靠脚本块正常结束后写输出文件，
        # exit 会让来宾侧进程直接退出，宿主收到「未产出输出」
        + "if (-not $f) { '未找到匹配控件（匹配总数 ' + $found.Count + '）' } else {\n"
        + "  '命中: [' + $f.Ctrl + '] ' + $f.Name + ' rect=' + $f.Rect\n"
        + "  try { " + act + " } catch { 'ERR: ' + $_.Exception.Message }\n"
        + "}\n"
        + "Start-Sleep -Seconds 2\n"
    )
    return guest_run(ps, timeout=300, interactive=True)


def main(argv: list[str]) -> int:
    op = argv[1] if len(argv) > 1 else "list"
    if op == "list":
        print(guest_run(
            _UIA_HEAD + r"""
foreach ($k in $AE::RootElement.FindAll($TS::Children, [System.Windows.Automation.Condition]::TrueCondition)) {
  $c = $k.Current; $r = $c.BoundingRectangle
  'hwnd=' + $c.NativeWindowHandle + ' pid=' + $c.ProcessId + ' name=[' + $c.Name + '] rect=' +
    [int]$r.X + ',' + [int]$r.Y + ',' + [int]$r.Width + 'x' + [int]$r.Height
}
""", timeout=240, interactive=True))
    elif op == "find":
        print(find(argv[2]))
    elif op in ("click", "invoke"):
        idx = int(argv[3]) if len(argv) > 3 else 1
        print(_click_action(argv[2], idx, op))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
