"""设备手册 MCP 服务端：让**本地模型自己**给设备建档、维护手册与查阅历史。

设计意图（用户要求）：设备手册不是仓库里写死的内容，而是模型在运行期
「遇到哪台设备、就为它建一份档」——首次接触时探测/问询得到的信息填进骨架，
配置验证有效后再把命令序列与踩过的坑沉淀回去。下次再操作同一台设备，
先读手册避免重复试错。

工具列表：
1. list_device_manuals()
   - 看哪些设备已有手册、哪些还没有（含在线状态与手册大小/更新时间）
2. read_device_manual(device)
   - 操作某台设备前先读它：常用配置、注意事项
3. create_device_manual(device, ...)
   - 首次接触某设备时建档（信息来自用户提供、探测结果或拓扑快照，**不要臆造**）
4. update_device_manual_section(device, section, text, ...)
   - 把验证有效的命令序列 / 注意事项写回手册（section 通常是「常用配置」「注意事项」）
5. recent_device_history(device, n)
   - 查看该设备最近的命令历史（历史由工具层自动记录，模型无需手写）

存储位置（均在用户工作目录，不进 git）：
    skills/<设备名>/SKILL.md             手册
    data/device_history/<设备名>.jsonl   命令历史（telnet/串口工具执行后自动追加）

运行方式（stdio，由 MCP 客户端拉起）：
    python mcp_tools/manual_server.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastmcp import FastMCP  # noqa: E402

from core import device_manual, device_registry  # noqa: E402

mcp = FastMCP("Network-Device-Manual")

MAX_MANUAL_CHARS = 12000     # 回给模型的正文上限，避免挤爆上下文


def _truncate(text: str, limit: int = MAX_MANUAL_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...（手册共 {len(text)} 字，已截断）"


@mcp.tool
def list_device_manuals() -> str:
    """列出设备建档情况：哪些设备已有手册、哪些还没建（含在线状态与手册更新时间）。

    首次处理某台设备前先调它，决定是「读已有手册」还是「先建档」。
    """
    try:
        known = device_registry.list_devices()
        has = {m["name"]: m for m in device_manual.list_manuals()}
    except Exception as e:
        return f"读取设备清单失败：{type(e).__name__}: {e}"

    lines: list[str] = []
    missing: list[str] = []
    for d in known:
        name = d.get("name") or d.get("key", "")
        m = has.get(name)
        if m:
            lines.append(f"  [{name}] 已有手册（{m['bytes']} 字节，更新于 {m['updated']}，"
                         f"历史 {m['history_lines']} 条）")
        else:
            missing.append(name)

    extra = [m for n, m in has.items() if n not in {d.get('name') for d in known}]
    out = [f"设备共 {len(known)} 台，已建档 {len(has)} 台："]
    out += lines or ["  （暂无手册）"]
    if missing:
        out.append(f"尚未建档（首次操作前建议先 create_device_manual）：{', '.join(missing)}")
    if extra:
        out.append("手册存在但不在当前清单里的设备："
                   + ", ".join(f"{m['name']}（{m['updated']}）" for m in extra))
    return "\n".join(out)


@mcp.tool
def read_device_manual(device: str) -> str:
    """读取某台设备的操作手册（常用配置、注意事项）。

    Args:
        device: 设备名，例如 SW1 / R1 / COM3
    """
    try:
        text = device_manual.read_manual(device)
    except device_manual.ManualError as e:
        return str(e)
    if not text:
        return (f"设备「{device}」还没有手册。建议先用 create_device_manual 建档，"
                f"再执行配置；配置验证有效后用 update_device_manual_section 沉淀。")
    return _truncate(text)


@mcp.tool
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
        return (f"已为 {device} 建立手册：skills/{device}/SKILL.md\n"
                f"———— 当前骨架 ————\n{_truncate(text)}")
    return (f"{device} 已有手册，未覆盖。内容如下（如需补充请用 "
            f"update_device_manual_section）：\n{_truncate(text)}")


@mcp.tool
def update_device_manual_section(device: str, section: str, text: str,
                                 mode: str = "append", title: str = "") -> str:
    """把内容写进设备手册的指定小节（手册不存在会自动建骨架）。

    典型用法：配置并被验证有效后，把命令序列沉淀进「常用配置」；
    执行中发现的坑（接口需先 shutdown、Eth-Trunk 两端需同配等）写进「注意事项」。

    Args:
        device: 设备名，例如 SW1
        section: 小节名，通常是「常用配置」或「注意事项」（也可「设备信息」）
        text: 要写入的内容，建议用代码块给出命令序列，并说明适用场景
        mode: append（追加，默认）或 replace（替换该小节原有内容）
        title: 可选小标题，如「链路聚合 Eth-Trunk 1」（会写成 `## 标题（日期）`）
    """
    try:
        whole = device_manual.update_section(device, section, text, mode=mode, title=title)
    except device_manual.ManualError as e:
        return f"写入失败：{e}"
    except OSError as e:
        return f"写入失败（文件错误）：{e}"
    return (f"已写入 {device} 手册的「{section}」小节。\n"
            f"———— 更新后的手册 ————\n{_truncate(whole)}")


@mcp.tool
def recent_device_history(device: str, n: int = 10) -> str:
    """查看某台设备最近的命令历史（工具层自动记录，无需手工维护）。

    Args:
        device: 设备名，例如 SW1
        n: 返回最近 n 条，默认 10
    """
    try:
        rows = device_manual.tail_history(device, n)
    except device_manual.ManualError as e:
        return str(e)
    if not rows:
        return f"设备「{device}」暂无命令历史（执行过命令后会自动记录）"
    lines = [f"{device} 最近 {len(rows)} 条命令："]
    for r in rows:
        # 兼容早期手工脚本写入的记录（只有 time/command/result/confirmed）
        if r.get("executed"):
            flag = "已执行"
        elif "executed" in r:
            flag = "未执行"
        else:
            flag = "—"
        lines.append(f"  [{r.get('time')}] {r.get('transport') or '—'} {flag} | {r.get('command')}")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
