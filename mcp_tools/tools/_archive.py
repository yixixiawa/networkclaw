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

失败不阻断命令结论，但**不再静默**：写结构化告警到 logs/archive_errors.log
（带 transport/target/session/命令前缀/异常类型），调用方据返回空串可区分
「归档失败」与「归档成功」，在回显里明示，不伪装成完整成功。
"""
from __future__ import annotations

import time

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)

from mcp_tools.tools._bootstrap import PROJECT_ROOT, relpath

# 归档失败告警文件（测试可 monkeypatch 此路径隔离）
WARN_LOG = PROJECT_ROOT / "logs" / "archive_errors.log"


def _warn(message: str) -> None:
    """尽力而为写一条告警行；写失败也绝不抛出（归档永远不干扰命令结论）。"""
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
    try:
        WARN_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(WARN_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:  # noqa: BLE001
        pass


def _archive(name_kwargs: dict, command: str, result: str, transport: str,
             target: str, level: str, confirmed: bool, executed: bool,
             extra: str = "", session: str = "") -> str:
    """统一归档入口：解析设备名 → 追加历史 → 返回可读相对路径（失败返回空串）。"""
    try:
        from core import device_manual, device_registry

        # 只有**真正执行成功**才登记「访问过该设备」。
        # 被 block 拦截、confirm 未确认、连接失败也照样归档命令（便于诊断），
        # 但不能把它们写进设备清单——否则设备页会出现一堆从没连上的地址。
        if executed:
            device_registry.record_access(transport, **name_kwargs)
        name = device_registry.resolve_name(transport, **name_kwargs)
        path = device_manual.append_history(
            name, command, result, transport=transport, target=target,
            level=level, confirmed=confirmed, executed=executed, extra=extra,
            session=session)
    except Exception as e:  # noqa: BLE001  归档失败不影响命令结论，但要可追溯
        _warn(f"archive_failed transport={transport} target={target} "
              f"session={session or '-'} executed={executed} "
              f"command={command[:120]!r} error={type(e).__name__}: {e}")
        return ""
    return relpath(path)


def record_telnet(host: str, port: int, command: str, level: str,
                  confirmed: bool, executed: bool, result: str = "",
                  extra: str = "", session: str = "") -> str:
    """归档一条 Telnet 命令（返回 `session/<sid>/skill/<设备>/history.jsonl` 相对路径）。"""
    return _archive({"host": host, "port": port}, command, result, "telnet",
                    f"{host}:{port}", level, confirmed, executed, extra, session)


def record_serial(port: str, command: str, level: str, confirmed: bool,
                  executed: bool, result: str = "", extra: str = "",
                  session: str = "") -> str:
    """归档一条串口命令（COM 口为身份）。"""
    return _archive({"serial_port": port}, command, result, "serial",
                    port, level, confirmed, executed, extra, session)
