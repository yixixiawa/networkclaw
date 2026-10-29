"""MCP 工具 update_device_manual_section：把内容写进手册的指定小节。

作用点：**沉淀**。配置并被验证有效后，把命令序列写进「常用配置」；
执行中发现的坑（接口需先 shutdown、Eth-Trunk 两端需同配等）写进「注意事项」。

手册不存在会自动建骨架——但正常流程应先 create_device_manual，避免骨架字段空着。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def update_device_manual_section(device: str, section: str, text: str,
                                 mode: str = "append", title: str = "",
                                 session: str = "") -> str:
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
    from core import device_manual
    from mcp_tools.tools._manual_common import truncate_manual, where

    try:
        whole = device_manual.update_section(device, section, text,
                                             mode=mode, title=title, session=session)
    except device_manual.ManualError as e:
        return f"写入失败：{e}"
    except OSError as e:
        return f"写入失败（文件错误）：{e}"
    return (f"已写入 {device} 手册的「{section}」小节（{where()}）。\n"
            f"———— 更新后的手册 ————\n{truncate_manual(whole)}")
