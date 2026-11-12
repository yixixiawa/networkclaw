"""VMware 来宾操作封装（vmrun）。

用途：在不登录虚拟机桌面的前提下，执行来宾命令、搬运文件。
凭据来源：环境变量 VM_GU / VM_GP（或项目根 `.env`）；源码不含任何口令，
缺失时直接报错（见 _require_cred）。

用法（命令行）：
    python tools/vm_guest.py run "<cmd 命令行>"
    python tools/vm_guest.py ls "<来宾目录>"
    python tools/vm_guest.py pull "<来宾路径>" "<宿主路径>"
    python tools/vm_guest.py push "<宿主路径>" "<来宾路径>"
    python tools/vm_guest.py ps
    python tools/vm_guest.py exists "<来宾路径>"

也可作为模块导入：
    from tools.vm_guest import guest_run, guest_ls, pull, push
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    """读配置：环境变量优先，缺失时回落到项目根 `.env`。

    为什么要有 .env 回落：这些工具经常被单独 `python -c` 调用，父进程没有
    加载过 .env；而凭据与路径**不能**写死在源码里（曾经的明文口令就留在这里）。
    """
    v = (os.environ.get(name) or "").strip()
    if v:
        return v
    try:
        from dotenv import dotenv_values

        return str(dotenv_values(BASE / ".env").get(name) or "").strip() or default
    except Exception:  # noqa: BLE001  .env 不可读就用默认值
        return default


VMRUN = _env("VM_VMRUN", r"D:\VMware\vmrun.exe")
VM_ROOT = _env("VM_ROOT", r"D:\virtualmachine")


class VmError(RuntimeError):
    """虚拟机操作失败。

    **必须定义在 discover_vmx() 之前**：它原来写在文件中部，而 discover_vmx()
    在模块导入期就会被调用（`VMX = discover_vmx()`），一旦路径不存在就抛
    `NameError: name 'VmError' is not defined`，把「虚拟机根目录不存在」这个
    真正有用的原因彻底盖掉（2026-10-23 实测踩到）。
    """
    pass


def _running_vmx() -> set[str]:
    """vmrun list 输出的正在运行 VMX（vmrun 输出是本地 ANSI，按 gbk 解码）。"""
    try:
        p = subprocess.run([VMRUN, "list"], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return set()
    txt = p.stdout.decode("gbk", "replace")
    return {ln.strip() for ln in txt.splitlines()[1:] if ln.strip().lower().endswith(".vmx")}


def discover_vmx() -> str:
    """定位 VMX：环境变量 > 正在运行的 > 目录里找到的第一个。

    换了实验机/换了虚拟机目录时不用再改代码（中文目录名在命令行里传参
    极易被编码搞坏，所以一律让 Python 自己发现）。
    """
    env = os.environ.get("VM_VMX")
    if env and Path(env).exists():
        return env
    # 目录漂移兜底：VM 被整个搬走（2026-10-23：VM_ROOT 里那台已挪到
    # "D:\virtual device\windows10\"）时，直接在 vmrun 的**运行中列表**里取，
    # 比在错误目录里报「根目录不存在」有用得多。
    running = _running_vmx()
    root = Path(VM_ROOT)
    if not root.exists():
        if running:
            return sorted(running)[0]
        raise VmError(f"虚拟机根目录不存在: {root}（且当前没有正在运行的 VM）")
    candidates = [p for p in root.rglob("*.vmx")
                  if ".bak" not in p.name.lower() and "vmx~" not in p.name.lower()]
    if not candidates:
        if running:
            return sorted(running)[0]
        raise VmError(f"{root} 下没有找到 .vmx")
    for p in candidates:
        if str(p) in running:
            return str(p)
    return str(sorted(candidates, key=lambda p: p.stat().st_mtime)[-1])


VMX = discover_vmx()

# 两组凭据（2026-10-01 实测，来宾 192.168.10.130）：
# - yixixiawa：日常交互账号，vmrun -interactive 拉图形界面必须用它（活动桌面在它会话里）
# - Administrator：**High Mandatory Level** 的完整管理员令牌，写 HKLM / 改 UAC 策略要用它；
#   yixixiawa 在 UAC 开启时是 Medium IL，改 HKLM 会被 ACCESS DENIED。
#
# 口令**不再写死在本文件**（2026-10 清理）：只从环境变量 / .env 读，
# 缺失时由 _require_cred() 直接报错，而不是静默用一个可能已失效的旧口令去撞锁。
USER_CRED = (_env("VM_GU", "yixixiawa"), _env("VM_GP"))
ADMIN_CRED = (_env("VM_ADMIN_U", "Administrator"), _env("VM_ADMIN_P"))

GU, GP = USER_CRED


def _require_cred(cred: tuple[str, str]) -> None:
    """缺口令直接失败（明确告诉用户配哪个变量），不拿空口令去调 vmrun。"""
    if not cred[1]:
        raise VmError(
            "未配置虚拟机来宾口令：请在 .env 或环境变量里设置 VM_GP（日常账号）"
            "或 VM_ADMIN_P（管理员账号）。口令不写进源码，也不写入日志。")

# 来宾侧的临时输出文件（每次命令后清理）
_REMOTE_TMP = r"C:\vm_guest_out.txt"


# 2026-10-01 实测（来宾 192.168.10.130）：vmrun 的来宾操作进程是 **High IL**
# （Administrators + High Mandatory Level），但 UAC 开启时它只有 **Medium 令牌**：
#   - 改 HKLM 策略、Set-ItemProperty HKLM、Disable-PnpDevice 一律 ACCESS DENIED
#   - 不能 -interactive 拉起图形程序
# 所以需要管理员权限的来宾操作，统一走 **计划任务以 SYSTEM 运行**（cred=USER 即可建任务）。
_SYSTEM_RUNNER = r"""
$taskName = 'NetworkClawSysTask'
$outFile  = 'C:\Windows\Temp\nc_sys_out.txt'
Remove-Item $outFile -Force -ErrorAction SilentlyContinue
$inner = $BODY
$b64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
$ps  = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
# 用一个包装命令行，把内层脚本以 base64 传入，避免引号地狱
$cmd = '"{0}" -NoProfile -NonInteractive -EncodedCommand {1} > "{2}" 2>&1' -f $ps, $b64, $outFile
try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}
$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c ' + $cmd)
$p = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $a -Principal $p -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
$i = 0
while ($i -lt 60) {
  Start-Sleep -Milliseconds 500
  $s = (Get-ScheduledTask -TaskName $taskName).State
  if ($s -ne 'Running') { break }
  $i++
}
try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}
if (Test-Path $outFile) { Get-Content $outFile -Raw } else { '<无输出>' }
"""


def run_as_system(body: str, timeout: int = 600) -> str:
    """以 SYSTEM 身份在来宾里执行 PowerShell 片段并返回输出。

    body 里**不要**出现子作用域里的 $BODY（会被本函数注入），也不要依赖交互桌面。

    实测（2026-10-01）：建计划任务本身也要管理员（普通会话 Register-ScheduledTask
    报「拒绝访问」0x80070005），所以必须走 **Administrator 凭据**的 vmrun 会话
    —— 注意不是 cred=False（不带凭据时 vmrun 报"需要有效用户名和密码"）。
    """
    import base64

    script = _SYSTEM_RUNNER.replace("$BODY", "$" + "BODY")
    # 用 base64 传 body，避免引号/换行被 task argument 拆散
    b64_body = base64.b64encode(body.encode("utf-8")).decode("ascii")
    script = script.replace("$" + "BODY", (
        f"[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64_body}'))"))
    global GU, GP
    old = (GU, GP)
    GU, GP = ADMIN_CRED
    try:
        # 必须 cred=True 且 **不带 -interactive**：vmrun 只有在不带 -interactive 时
        # 才对任意账号放行；带 -interactive 时要求账号与当前交互登录用户一致
        # （实测报「指定的客户机用户与当前以交互方式登录的用户不匹配」）。
        return guest_run(script, timeout=timeout, cred=True)
    finally:
        GU, GP = old


def use_admin(flag: bool = True) -> None:
    """切换当前进程后续 vmrun 调用使用的凭据（管理员 / 普通用户）。"""
    global GU, GP
    GU, GP = ADMIN_CRED if flag else USER_CRED


def as_admin(fn, *a, **kw):
    """用管理员凭据执行一段代码，结束后恢复（用于写 HKLM、改系统策略）。"""
    global GU, GP
    old = (GU, GP)
    use_admin(True)
    try:
        return fn(*a, **kw)
    finally:
        GU, GP = old


def _vmrun(args: list[str], timeout: int = 180,
           cred: bool = True) -> tuple[int, str, str]:
    """直接调用 vmrun，返回 (returncode, stdout, stderr)。

    cred=False 时不带 -gu/-gp：来宾操作由 VMware Tools 服务（SYSTEM）执行，
    进程完整性级别为 High —— 这是向提权程序（eNSP）注入输入的唯一通道。
    """
    if cred:
        _require_cred((GU, GP))
    pre = ["-gu", GU, "-gp", GP] if cred else []
    cmd = [VMRUN, "-T", "ws", *pre, *args]

    # 输出必须落到**临时文件**而不是管道。
    # subprocess.run(capture_output=True) 超时后会 kill vmrun，但紧接着的
    # communicate() 仍要等管道 EOF；只要有别的进程（来宾侧残留进程、VMware 后台
    # 进程）继承了管道写端，就会**永久挂起**——实测批量任务就是这样卡死十几分钟的：
    # 进程 CPU 停在 0.01s、看不到 vmrun 子进程、日志一动不动。改用文件彻底规避。
    fd_o, path_o = tempfile.mkstemp(prefix="vmrun_o_")
    fd_e, path_e = tempfile.mkstemp(prefix="vmrun_e_")
    os.close(fd_o)
    os.close(fd_e)
    try:
        with open(path_o, "wb") as fo, open(path_e, "wb") as fe:
            p = subprocess.Popen(cmd, stdout=fo, stderr=fe)
            try:
                rc = p.wait(timeout=timeout)
            except subprocess.TimeoutExpired as e:  # noqa: PERF203
                p.kill()
                try:
                    p.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    pass
                raise VmError(f"vmrun 超时（{timeout}s）: {args[0]}") from e
        out = Path(path_o).read_bytes().decode("utf-8", "replace")
        err = Path(path_e).read_bytes().decode("utf-8", "replace")
    finally:
        for f in (path_o, path_e):
            try:
                os.unlink(f)
            except OSError:
                pass
    return rc, out, err


def _check(rc: int, out: str, err: str) -> str:
    if rc != 0 or "Error:" in out or "Error:" in err:
        raise VmError(f"vmrun 失败 rc={rc}\nstdout={out}\nstderr={err}")
    return out


# ---------------------------------------------------------------- 基础操作

_PWSH = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def _encode_ps(script: str) -> str:
    """PowerShell -EncodedCommand：UTF-16LE + base64。

    这样脚本作为**单个无空格无引号的 token** 传给 vmrun，彻底规避 vmrun
    重新拼接命令行导致的参数被空格拆散问题。
    """
    import base64

    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def guest_run(script: str, timeout: int = 300, cwd: str | None = None,
              interactive: bool = False, cred: bool = True) -> str:
    """在来宾里执行 PowerShell 脚本片段，返回其输出（含错误流）。    实测约束（本机环境）：
    - `runProgramInGuest ... cmd.exe` 一律返回 1（非交互会话起不来），必须用 powershell.exe
    - vmrun 不回传来宾 stdout，输出须落地成文件再拷回
    - 脚本必须走 -EncodedCommand，否则含空格/引号的 -Command 会被截断（静默失败）
    - 需要拉起**图形界面**程序（eNSP 等）时必须 interactive=True，
      否则进程落在会话 0，窗口不可见也无法做 UI 自动化
    """
    import uuid

    remote_out = rf"C:\Windows\Temp\vmout_{uuid.uuid4().hex[:8]}.txt"
    if cwd:
        script = f'Set-Location -LiteralPath "{cwd}"; {script}'
    wrapped = (
        "$ErrorActionPreference='Continue'; "
        "$ProgressPreference='SilentlyContinue'; "
        f"$r = (& {{ {script} }} *>&1 | Out-String -Width 400); "
        f"[IO.File]::WriteAllText('{remote_out}', $r, [Text.UTF8Encoding]::new($false))"
    )

    run_args = ["runProgramInGuest", VMX]
    if interactive:
        run_args.append("-interactive")
    # -WindowStyle Hidden：交互模式下 powershell 会分配可见控制台，别让它挡在桌面上
    run_args += [_PWSH, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                 "-EncodedCommand", _encode_ps(wrapped)]
    rc, out, err = _vmrun(run_args, timeout=timeout, cred=cred)

    host_tmp = Path(tempfile.gettempdir()) / f"vmout_{uuid.uuid4().hex[:6]}.txt"
    rc2, out2, err2 = _vmrun(
        ["copyFileFromGuestToHost", VMX, remote_out, str(host_tmp)],
        timeout=120, cred=cred,
    )
    if rc2 != 0 or not host_tmp.exists():
        return (f"<来宾命令未产出输出> rc={rc} run={out.strip()}{err.strip()} "
                f"| copy rc={rc2} {out2.strip()}{err2.strip()}")

    data = host_tmp.read_bytes()
    host_tmp.unlink(missing_ok=True)
    # 清理来宾临时文件（best-effort）
    _vmrun(["deleteFileInGuest", VMX, remote_out], timeout=60)
    text = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = data.decode("utf-8", "replace")
    return text.replace("\r\n", "\n")


def guest_run_elevated(script: str, timeout: int = 300, cred: bool = True) -> str:
    """以 **High IL 在交互会话里**执行 PowerShell 脚本（给键鼠注入用）。

    背景（2026-10-01 实测，来宾 192.168.10.130，UAC 提示已关）：
    - `guest_run(interactive=True)` 的来宾进程是 **Medium IL**（whoami /groups 可见），
      而 eNSP 现在以管理员提权运行（路由器要驱动 VirtualBox，不能降权）；
    - UIPI 会把 Medium → High 的注入（SetForegroundWindow / mouse_event /
      keybd_event）**静默丢弃**，表现为 setfg=False、Ctrl+A 落到别的窗口；
    - UAC 提示策略=0 时，Medium 进程 ShellExecute「runas」会**静默放行**——
      launch() 就是这样把 eNSP 提权拉起的。
    所以：先把完整脚本 push 成来宾里的 .ps1，再让一个交互会话里的「启动器」
    Start-Process -Verb RunAs 拉起 High IL 的 powershell 跑它，输出落文件后拷回。
    脚本走**文件**而不是 -EncodedCommand：vmrun 命令行长度有限（实测稍长的
    EncodedCommand 直接报 bora/lib/string/str.c:443 Buffer too small）。

    依赖：来宾的 ConsentPromptBehaviorAdmin=0（否则 RunAs 会等一个没人点的 UAC 框）。
    """
    import uuid

    token = uuid.uuid4().hex[:8]
    remote_out = rf"C:\Windows\Temp\vmelev_out_{token}.txt"
    remote_ps = rf"C:\Windows\Temp\vmelev_run_{token}.ps1"
    worker = (
        "$ErrorActionPreference='Continue'\n"
        "$ProgressPreference='SilentlyContinue'\n"
        f"$r = (& {{\n{script}\n}} *>&1 | Out-String -Width 400)\n"
        f"[IO.File]::WriteAllText('{remote_out}', $r, [Text.UTF8Encoding]::new($false))\n"
    )
    host_ps = Path(tempfile.gettempdir()) / f"vmelev_run_{token}.ps1"
    host_ps.write_text(worker, encoding="utf-8-sig")  # 带 BOM，防来宾 PS 按 ANSI 读中文
    try:
        push(str(host_ps), remote_ps)
    finally:
        host_ps.unlink(missing_ok=True)

    launcher = (
        "$ErrorActionPreference='Continue'; "
        f"$p = Start-Process -FilePath '{_PWSH}' -Verb RunAs -PassThru "
        f"-ArgumentList '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',"
        # 不加 -WindowStyle Hidden 会弹可见控制台：抢占前台、甚至挡住注入的点击
        f"'-WindowStyle','Hidden','-File','{remote_ps}'; "
        "if (-not $p) { 'ELEV-FAIL: Start-Process 未返回进程' } "
        f"elseif (-not ($p.WaitForExit({timeout * 1000}))) {{ 'ELEV-TIMEOUT' }} "
        "else { 'ELEV-OK rc=' + $p.ExitCode }"
    )
    rc, out, err = _vmrun(
        ["runProgramInGuest", VMX, "-interactive", _PWSH,
         "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
         "-EncodedCommand", _encode_ps(launcher)],
        timeout=timeout + 60, cred=cred,
    )
    if rc != 0:
        return f"<提权启动失败> rc={rc} {out.strip()}{err.strip()}"

    host_tmp = Path(tempfile.gettempdir()) / f"vmelev_out_{uuid.uuid4().hex[:6]}.txt"
    rc2, _o2, _e2 = _vmrun(
        ["copyFileFromGuestToHost", VMX, remote_out, str(host_tmp)],
        timeout=120, cred=cred,
    )
    for f in (remote_ps, remote_out):
        _vmrun(["deleteFileInGuest", VMX, f], timeout=60)
    if rc2 != 0 or not host_tmp.exists():
        return f"<提权命令未产出输出> run={out.strip()}"
    data = host_tmp.read_bytes()
    host_tmp.unlink(missing_ok=True)
    return data.decode("utf-8", "replace").replace("\r\n", "\n")


def guest_ls(path: str) -> str:
    """列目录。"""
    return guest_run(
        f'Get-ChildItem -LiteralPath "{path}" -Force | '
        'Format-Table Mode,Length,Name -AutoSize | Out-String -Width 200'
    )


def pull(guest_path: str, host_path: str) -> None:
    """从来宾复制文件到宿主。"""
    Path(host_path).parent.mkdir(parents=True, exist_ok=True)
    rc, out, err = _vmrun(
        ["copyFileFromGuestToHost", VMX, guest_path, os.path.abspath(host_path)],
        timeout=600,
    )
    _check(rc, out, err)


def push(host_path: str, guest_path: str) -> None:
    """从宿主复制文件到来宾。"""
    rc, out, err = _vmrun(
        ["copyFileFromHostToGuest", VMX, os.path.abspath(host_path), guest_path],
        timeout=600,
    )
    _check(rc, out, err)


def ps() -> str:
    rc, out, err = _vmrun(["listProcessesInGuest", VMX])
    return _check(rc, out, err)


def exists(guest_path: str) -> bool:
    rc, out, _ = _vmrun(["fileExistsInGuest", VMX, guest_path])
    return "exists" in out.lower() and "does not exist" not in out.lower()


def capture_screen(host_path: str) -> None:
    """截取来宾屏幕到宿主机文件（PNG），用于验证 GUI 自动化效果。"""
    Path(host_path).parent.mkdir(parents=True, exist_ok=True)
    rc, out, err = _vmrun(["captureScreen", VMX, os.path.abspath(host_path)], timeout=180)
    _check(rc, out, err)


def is_running() -> str:
    p = subprocess.run([VMRUN, "list"], capture_output=True, timeout=60)
    return p.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------- CLI

def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    op = argv[1]
    if op == "run":
        print(guest_run(argv[2]))
    elif op == "runx":
        print(guest_run(argv[2], interactive=True))
    elif op == "screen":
        capture_screen(argv[2])
        print(f"screen -> {argv[2]}")
    elif op == "ls":
        print(guest_ls(argv[2]))
    elif op == "pull":
        pull(argv[2], argv[3])
        print(f"pulled -> {argv[3]}")
    elif op == "push":
        push(argv[2], argv[3])
        print(f"pushed -> {argv[3]}")
    elif op == "ps":
        print(ps())
    elif op == "exists":
        print("YES" if exists(argv[2]) else "NO")
    elif op == "vms":
        print(is_running())
    else:
        print(f"未知操作: {op}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
