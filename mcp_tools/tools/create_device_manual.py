"""MCP 工具 create_device_manual：为设备首次建档。

作用点：**建档**。信息必须来自用户提供 / 探测结果（display version 等）/
拓扑识读结论，**不得臆造**；不确定的字段留空，手册里会写「（待确认）」。

顺带能力：传 transport+host+port（或 serial_port）可把设备名绑定到地址，
绑定后命令历史会自动归到该设备名下（见 core/device_registry.bind_name）。

顺序很重要（2026-10 修）：**先绑定、再建档**。绑定可能因为重名而改名
（同名已被另一台占用时加 `-<端口>` 后缀），若先建档就会留下一份叫 A 的手册，
而后续历史写进 A-2003——两份记录各查一半。所以用绑定返回的实际名字建档。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def create_device_manual(device: str, vendor: str = "", model: str = "",
                         address: str = "", role: str = "", login: str = "",
                         note: str = "", transport: str = "", host: str = "",
                         port: int = 0, serial_port: str = "", session: str = "") -> str:
    """为设备首次建档（生成手册骨架并写入基本信息）。

    信息必须来自用户提供、探测结果（display version 等）或拓扑识读结论，**不得臆造**；
    不确定的字段留空即可，手册里会写成「（待确认）」，后续可再更新。

    Args:
        device: 设备名，例如 SW1（**必须是名字，不能是 IP:端口**；地址请放 address 或 host/port）
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

    if not (device or "").strip():
        return "建档失败：device 不能为空。请给设备起个名字（如 SW1），地址放在 address 里。"

    requested = device.strip()
    # COM3 这类 Windows 保留名本身是合法设备标识（串口号），但当不了目录名。
    # 直接拒收会让串口设备永远无法建档，这里与 device_registry 保持一致加 -serial。
    if session_skills.is_reserved(requested):
        requested = f"{requested}-serial"
    # 先绑定地址 → 拿到实际生效的名字（可能与请求的不同：重名会自动加后缀）
    name = requested
    renamed = ""
    if transport in ("telnet", "serial"):
        effective = device_registry.bind_name(
            transport, requested, host=host, port=int(port or 0),
            serial_port=serial_port)
        if effective:
            if effective.lower() != requested.lower():
                renamed = (f"注意：名字「{requested}」已被另一台设备占用，"
                           f"本设备改用「{effective}」建档（历史也记在它名下）。\n")
            name = effective

    try:
        text, created = device_manual.ensure_manual(
            name, vendor=vendor, model=model, address=address,
            login=login, role=role, note=note, session=session)
    except device_manual.ManualError as e:
        hint = ""
        if ":" in requested or "/" in requested or "\\" in requested:
            hint = ("\n看起来你把地址当成了设备名。请改成设备名（如 SW1），"
                    "地址放 address 参数，并用 transport/host/port 绑定。")
        return f"建档失败：{e}{hint}"
    except OSError as e:
        return f"建档失败（写入错误）：{e}"

    if created:
        path = f"session/{session or session_skills.current()}/skill/{name}/SKILL.md"
        # ---- Wiki 化（新设备建档即生成说明书）----
        # 抓取当前配置（只读）+ 实测拓扑邻居 → 交给模型生成 Markdown 说明 →
        # 写进「拓扑关系 / 配置基线」小节。任一步失败都只降级、不阻断建档
        # （骨架仍在，模型可稍后用 update_device_manual_section 手工补）。
        wiki_tail = ""
        if transport == "telnet" and host:
            try:
                from core import device_manual as dm

                config = dm.fetch_current_config(host, port=int(port or 0),
                                                 timeout=30.0)
                topo = dm.topology_for_device(name)
                res = dm.wiki_enrich(name, config, topo, session=session)
                if res["ok"]:
                    wiki_tail = (f"\n———— Wiki 自动生成 ————\n"
                                 f"已根据当前配置与实测拓扑生成说明书，写入小节："
                                 f"{'、'.join(res['written'])}。"
                                 f"后续对话可直接引用该手册作为背景。")
                else:
                    wiki_tail = (f"\n———— Wiki 自动生成未完成 ————\n{res['note']}"
                                 f"（骨架已保留，可稍后手工补全）")
            except Exception as e:  # noqa: BLE001  Wiki 化是增强项，失败不阻断
                wiki_tail = (f"\n———— Wiki 自动生成未完成 ————\n"
                             f"{type(e).__name__}: {e}（设备不可达或超时；"
                             f"骨架已保留，可稍后手工补全）")
        return (f"{renamed}已为 {name} 建立手册（{where()}）：{path}\n"
                f"———— 当前骨架 ————\n{truncate_manual(text)}{wiki_tail}")
    return (f"{renamed}{name} 在本会话已有手册，未覆盖。内容如下（如需补充请用 "
            f"update_device_manual_section）：\n{truncate_manual(text)}")
