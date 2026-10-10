"""串口（Console）MCP 服务端：让智能体通过串口线连接到目标设备执行命令。

工具列表：
1. list_serial_ports()
   - 列出本机可用串口（COM3 等），执行前先看这个确认端口号
2. classify_command(command)
   - 只做风险分级、不执行：allow / confirm / block
   - 建议模型在下发配置命令前先调它，这样能提前把影响讲清楚
3. exec_command(command, port, baudrate, confirm, timeout)
   - 打开串口 → 执行命令 → 返回回显
   - 安全策略（见 core/command_guard.py）：
       allow   display / show / ping / tracert 等只读命令 → 直接执行
       confirm sysname / vlan / interface 等配置命令 → 必须确认；未带 confirm=true 只返回风险说明
       block   undo / shutdown / delete / reset / reboot 等 → 直接拦截，任何参数都不执行
   - 每次裁决都写入 logs/command_audit.log

典型用法：
    exec_command("display version", port="COM3")
    exec_command("sysname SW-Core-01", port="COM3")                 # 第一次会被拦下要确认
    exec_command("sysname SW-Core-01", port="COM3", confirm=True)   # 用户同意后再执行

运行方式（stdio，由 MCP 客户端拉起）：
    python mcp_tools/device_server.py
"""
import sys
from pathlib import Path

# 保证从任意工作目录被 MCP 客户端拉起时都能导入 core 包
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastmcp import FastMCP  # noqa: E402

from core import device_conn  # noqa: E402
from core.command_guard import LEVEL_CN, audit, audit_tail, check, split_commands  # noqa: E402

mcp = FastMCP("Network-Device-Serial")

MAX_OUTPUT = 6000          # 回显过长会挤爆模型上下文，超出部分截断
DEFAULT_BAUDRATE = 9600    # 网络设备 Console 口默认波特率


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return (text[:limit]
            + f"\n...（回显共 {len(text)} 字，已截断；如需完整内容可配合 display ... | include 过滤）")


def _record(port: str, command: str, level: str, confirmed: bool,
            executed: bool, result: str = "", extra: str = "") -> str:
    """访问登记 + 命令历史归档（确定性落盘，失败静默不影响执行）；返回归档文件名"""
    name = ""
    try:
        from core import device_manual, device_registry
        device_registry.record_access("serial", serial_port=port)
        name = device_registry.resolve_name("serial", serial_port=port)
        device_manual.append_history(name, command, result, transport="serial",
                                     target=port, level=level, confirmed=confirmed,
                                     executed=executed, extra=extra)
    except Exception:
        return ""
    return f"data/device_history/{name}.jsonl" if name else ""


@mcp.tool
def list_serial_ports() -> str:
    """列出本机可用串口设备（执行串口命令前先用它确认端口号）。"""
    try:
        ports = device_conn.list_serial_ports()
    except Exception as e:
        return f"串口枚举失败：{type(e).__name__}: {e}"
    if not ports:
        return ("未发现可用串口。请确认：① 串口线/USB 转串口已插入；"
                "② 驱动已安装；③ 端口未被 SecureCRT / 串口助手等程序占用。")
    lines = [f"发现 {len(ports)} 个串口："]
    for p in ports:
        lines.append(f"  - {p['device']}：{p['description']}（{p['hwid']}）")
    return "\n".join(lines)


@mcp.tool
def classify_command(command: str) -> str:
    """判断一条设备命令的风险等级，不执行任何操作。

    分级规则：allow（只读，可直接执行）/ confirm（配置类，需用户同意）/ block（破坏性，禁止执行）。

    Args:
        command: 待评估的命令，例如 "undo vlan 100"
    """
    from core.command_guard import classify
    if not (command or "").strip():
        return "command 不能为空"
    return classify(command)["text"]


@mcp.tool
def exec_command(command: str, port: str, baudrate: int = DEFAULT_BAUDRATE,
                 confirm: bool = False, timeout: int = 20,
                 disable_paging: bool = True) -> str:
    """通过串口（Console）在目标设备上执行一条命令。

    Args:
        command: 要执行的命令；多条命令请分次调用，不要用分号串联
        port: 串口号，例如 COM3（先用 list_serial_ports 查询）
        baudrate: 波特率，默认 9600
        confirm: 仅当该命令被判定为「需确认」且用户已明确同意时才传 true
        timeout: 等待回显的超时秒数，默认 20（ping 等耗时命令可加大）
        disable_paging: 是否自动关闭长回显分页，默认 true
    """
    command = (command or "").strip()
    if not command:
        return "command 不能为空"
    if not (port or "").strip():
        return "port 不能为空，请先用 list_serial_ports 查询可用串口"

    allowed, message, decision = check(command, confirmed=confirm)
    if not allowed:
        audit(command, decision, transport="serial", target=port,
              confirmed=confirm, executed=False)
        _record(port.strip().upper(), command, decision["level"], confirm, False,
                result=message)
        return message

    sess = None
    try:
        sess = device_conn.open_serial(port, baudrate=baudrate, timeout=max(5, timeout),
                                       disable_paging=disable_paging)
        # 支持 `;`/换行串联的多条命令：同一会话内逐条执行（视图状态自然延续）
        parts = split_commands(command)
        if len(parts) == 1:
            output = sess.exec_command(command, timeout=max(5, timeout))
        else:
            chunks = []
            for part in parts:
                r = sess.exec_command(part, timeout=max(5, timeout))
                chunks.append(f"$ {part}\n{r}" if r else f"$ {part}\n(无回显)")
            output = "\n".join(chunks)
        audit(command, decision, transport="serial", target=port,
              confirmed=confirm, executed=True)
        filed = _record(port.strip().upper(), command, decision["level"], confirm, True,
                        result=output)
    except Exception as e:
        audit(command, decision, transport="serial", target=port,
              confirmed=confirm, executed=False, extra=f"{type(e).__name__}: {e}")
        _record(port.strip().upper(), command, decision["level"], confirm, False,
                result=f"{type(e).__name__}: {e}")
        return f"串口执行失败：{type(e).__name__}: {e}"
    finally:
        if sess is not None:
            sess.close()

    tail = f"\n（已记入 {filed}）" if filed else ""
    return (f"[{LEVEL_CN[decision['level']]}] {port} 执行：{command}\n"
            f"———— 回显 ————\n{_truncate(output) if output else '(设备无回显)'}{tail}")


@mcp.tool
def recent_audit(n: int = 10) -> str:
    """查看最近的命令执行审计记录（谁通过什么通道下发了什么命令、是否被拦截）。

    Args:
        n: 返回最近 n 条，默认 10
    """
    rows = audit_tail(max(1, n))
    if not rows:
        return "暂无审计记录"
    lines = [f"最近 {len(rows)} 条命令审计："]
    for r in rows:
        flag = "已执行" if r.get("executed") else "未执行"
        lines.append(
            f"  [{r.get('time')}] {r.get('transport')} → {r.get('target')} | "
            f"{LEVEL_CN.get(r.get('level'), r.get('level'))} | {flag} | {r.get('command')}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
