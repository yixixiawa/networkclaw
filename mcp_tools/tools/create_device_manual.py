"""MCP 工具 create_device_manual：为设备首次建档。

作用点：**建档**。信息必须来自用户提供 / 探测结果（display version 等）/
拓扑识读结论，**不得臆造**；不确定的字段留空，手册里会写「（待确认）」。

顺带能力：传 transport+host+port（或 serial_port）可把设备名绑定到地址，
绑定后命令历史会自动归到该设备名下（见 core/device_registry.bind_name）。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def create_device_manual(device: str, vendor: str = "", model: str = "",
                         address: str = "", role: str = "", login: str = "",
                         note: str = "", transport: str = "", host: str = "",
                         port: int = 0, serial_port: str = "") -> str:
    """为设备首次建档（生成手册骨架并写入基本信息）。

    信息必须来自用户提供、探测结果（display version 等）或拓扑识读结论，**不得臆造**；
    不确定的字段留空即可，手册里会写成「（待确认）」，后续可再更新。

    Args:
        device: 设备名，例如 SW1（若用户未给名字，可依据型号与角色命名，如 SW3）
        vendor: 厂商，如 Huawei / H3C / Cisco
        model: 型号，如 S5700-28C-HI / AR2220
        address: 管理地址，如 192.168.10.128:2003 或 COM3
        role: 角色，如「接入交换机」「出口路由器」
        login: 登录方式，如「Telnet，无凭据」（**密码不要写入**）
        note: 备注
        transport/host/port/serial_port: 可选，用于把设备名绑定到地址（绑定后命令历史
            会自动归到该设备名下，例如 host=192.168.10.128 port=2003）
    """
    from core import device_manual, device_registry, session_skills
    from mcp_tools.tools._manual_common import truncate_manual, where

    try:
        text, created = device_manual.ensure_manual(
            device, vendor=vendor, model=model, address=address,
            login=login, role=role, note=note)
    except device_manual.ManualError as e:
        return f"建档失败：{e}"
    except OSError as e:
        return f"建档失败（写入错误）：{e}"

    if transport in ("telnet", "serial"):
        device_registry.bind_name(transport, device, host=host,
                                  port=int(port or 0), serial_port=serial_port)

    if created:
        path = f"session/{session_skills.current()}/skill/{device}/SKILL.md"
        return (f"已为 {device} 建立手册（{where()}）：{path}\n"
                f"———— 当前骨架 ————\n{truncate_manual(text)}")
    return (f"{device} 在本会话已有手册，未覆盖。内容如下（如需补充请用 "
            f"update_device_manual_section）：\n{truncate_manual(text)}")
