"""命令历史归档：把每次下发（无论成功/被拦/异常）确定性落盘。

为什么放在工具层而不是靠模型自觉：
    模型经常「执行完了」就往下走，不写记录。历史一旦断档，复盘、SFT 数据集、
    工作流数据报告（core/data_report.py）都会缺料。所以由工具层在每次调用后
    主动归档，模型无需配合。

设备名解析链（见 core/device_registry.resolve_name）：
    访问登记绑定的名字 > 种子清单（host:port 匹配）> 地址兜底
    绑定名优先是关键：eNSP 的 console 端口号会随拓扑变化，静态清单容易错配。

两种通道：
    record_telnet(host, port, ...)    Telnet：以 host:port 为身份
    record_serial(port, ...)          串口：以 COMx 为身份

失败静默：归档是「锦上添花」，绝不能因为它抛异常而影响命令本身的结论。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)

from mcp_tools.tools._bootstrap import relpath


def _archive(name_kwargs: dict, command: str, result: str, transport: str,
             target: str, level: str, confirmed: bool, executed: bool,
             extra: str = "") -> str:
    """统一归档入口：解析设备名 → 追加历史 → 返回可读相对路径（失败返回空串）。"""
    try:
        from core import device_manual, device_registry

        device_registry.record_access(transport, **name_kwargs)
        name = device_registry.resolve_name(transport, **name_kwargs)
        path = device_manual.append_history(
            name, command, result, transport=transport, target=target,
            level=level, confirmed=confirmed, executed=executed, extra=extra)
    except Exception:  # noqa: BLE001  归档失败不影响命令结论
        return ""
    return relpath(path)


def record_telnet(host: str, port: int, command: str, level: str,
                  confirmed: bool, executed: bool, result: str = "",
                  extra: str = "") -> str:
    """归档一条 Telnet 命令（返回 `session/<sid>/skill/<设备>/history.jsonl` 相对路径）。"""
    return _archive({"host": host, "port": port}, command, result, "telnet",
                    f"{host}:{port}", level, confirmed, executed, extra)


def record_serial(port: str, command: str, level: str, confirmed: bool,
                  executed: bool, result: str = "", extra: str = "") -> str:
    """归档一条串口命令（COM 口为身份）。"""
    return _archive({"serial_port": port}, command, result, "serial",
                    port, level, confirmed, executed, extra)
