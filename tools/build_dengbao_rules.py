"""等保2.0 规则台账生成器 —— 单一数据源。

为什么用「脚本 + 数据表」而不是手写 30 多个 YAML：
    规则条目的每个字段都能追溯到三份资料的某一行，手写 YAML 迟早会漂移
    （改一条改不全、severity 与权重对不上）。这里把「取哪一行」写成代码，
    生成器统一负责：权重推导 severity、命令出处核对、索引汇总、一致性自检。

数据来源（严格限定这三份 xlsx，见 RULES 里每条的 source 字段）：
    A = 等保2.0初级教材 测评操作.xlsx
    B = 等保2.0差距评估与整改建议.xlsx
    C = 等保2.0一~三级测评项得分及权重-参考材料.xlsx
命令出处白名单：
    D = knowledge/command_templates.csv  +  A 的「测评方法/预期结果」原文（由
        tools/_verify_remediation_source.SourceIndex 逐条核验，缺一即报错）
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

import openpyxl
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from _verify_remediation_source import SourceIndex  # noqa: E402

MAT = Path(r"D:\net-security-teach\等级评估\等保材料-课堂1.0")
X_A = MAT / "等保2.0初级教材 测评操作.xlsx"
X_B = MAT / "等保2.0差距评估与整改建议.xlsx"
X_C = MAT / "等保2.0一~三级测评项得分及权重-参考材料.xlsx"

OUT_DIR = ROOT / "knowledge" / "compliance" / "dengbao_rules"


# ---------------------------------------------------------------- 资料读取
def _load(path: Path, sheet: str) -> list[list[str]]:
    ws = openpyxl.load_workbook(path, data_only=True)[sheet]
    out = []
    for r in range(1, ws.max_row + 1):
        row = []
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            row.append("" if v is None else str(v).strip())
        out.append(row)
    return out


SRC_LINES = ROOT / "knowledge" / "compliance" / "dengbao_source_lines.json"


def _kb_blob() -> str:
    parts = []
    for sheet in ("安全区域边界", "安全计算环境"):
        for row in _load(X_A, sheet):
            parts.extend(row)
    return "\n".join(parts)


def _dump_source_lines() -> None:
    """把两份 xlsx 的原文逐行抽出来存档。

    为什么要存档而不是让测试直接读 xlsx：
        项目 venv 没有 openpyxl，测试直接读会 ImportError → 被 skip，
        而「命令不许编造」恰恰是最不能跳过的约束。存档是纯 JSON，
        任何环境都能读，测试也就不再依赖 openpyxl。
    """
    seen: set[str] = set()
    lines: list[str] = []
    targets = [
        (X_A, ("安全区域边界", "安全计算环境")),
        (X_B, ("安全计算环境-网络设备", "安全计算环境-安全设备")),
    ]
    for path, sheets in targets:
        for sheet in sheets:
            if sheet not in openpyxl.load_workbook(path, read_only=True).sheetnames:
                continue
            for row in _load(path, sheet):
                for cell in row:
                    for line in cell.splitlines():
                        line = line.strip()
                        if line and line.lower() not in seen:
                            seen.add(line.lower())
                            lines.append(line)
    SRC_LINES.write_text(
        json.dumps({"source": [X_A.name, X_B.name], "lines": lines},
                   ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------- severity 推导
# 依据：C 表的第二级/第三级权重列（c7 / c9）。
# 权重 1 → high（核心必测项，缺失直接判定不符合）
# 权重 0.7 → medium
# 权重 0.4 → low（GB/T 22239 里带「可」字的增强项）
SEVERITY_MAP = {"1": "high", "0.7": "medium", "0.4": "low"}


def severity_of(weight: float) -> str:
    key = f"{weight:.1f}".rstrip("0").rstrip(".") if isinstance(weight, float) else str(weight)
    key = {"1.0": "1", "0.7": "0.7", "0.4": "0.4"}.get(key, key)
    if key not in SEVERITY_MAP:
        raise ValueError(f"未知权重 {weight!r}，无法推导 severity")
    return SEVERITY_MAP[key]


# ---------------------------------------------------------------- 规则定义
# 字段含义见 docs 输出契约。check.type 仅五种；check.target 用配置文本里的定位锚。
# weight 取 C 表第三级权重（三级是当前主流定级目标）；L2 权重一并记录在 weight_l2，
# 便于二级系统复用时不必回头翻表。
RULES: list[dict] = []


def rule(**kw):
    RULES.append(kw)


# ================================================================ 安全区域边界 / 访问控制
# A 表 sheet=安全区域边界 行 6~10；C 表行 43~47
BORDER_AC_SRC = "《等保2.0初级教材 测评操作.xlsx》sheet「安全区域边界」第{}行"

rule(
    id="DB-BND-AC-01",
    vendor="any",
    device_type="firewall",
    category="安全区域边界-访问控制",
    control_point="访问控制",
    requirement="a)应在网络边界或区域之间根据访问控制策略设置访问控制规则，默认情况下除允许通信外受控接口拒绝所有通信",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="《等保2.0初级教材 测评操作.xlsx》sheet「安全区域边界」第6行「a)」"
           "；权重见《等保2.0一~三级测评项得分及权重-参考材料.xlsx》行43（二级=1，三级=1）",
    check=dict(
        type="config_regex",
        target="running-config",
        expect="受控接口上存在已应用的访问控制列表，且列表末尾为显式拒绝（白名单语义）",
        pattern=r"(?is)access-list\s+\d+.*?deny\s+ip\s+any\s+any|"
                r"ip\s+access-group\s+\d+\s+(?:in|out)|"
                r"packet-filter\s+\d+\s+(?:inbound|outbound)|"
                r"traffic-filter\s+(?:inbound|outbound)\s+acl\s+\d+",
    ),
    remediation=[
        "access-list 100 deny ip any any",
        "ip access-group 100 in",
        "acl 3000",
        "traffic-filter outbound acl 3000",
    ],
    evidence_hint="display current-configuration / show running-config 中受控接口段落；"
                  "需能看到 access-group / packet-filter / traffic-filter 已绑定到接口方向，"
                  "且 ACL 最后一条为 deny",
)

rule(
    id="DB-BND-AC-02",
    vendor="any",
    device_type="firewall",
    category="安全区域边界-访问控制",
    control_point="访问控制",
    requirement="b)应删除多余或无效的访问控制规则，优化访问控制列表，并保证访问控制规则数量最小化",
    weight_l3=0.7, weight_l2=0.7, weight_level=3,
    source="《等保2.0初级教材 测评操作.xlsx》sheet「安全区域边界」第7行「b)」"
           "；权重见《…权重-参考材料.xlsx》行44（二级=0.7，三级=0.7）",
    # 为什么不用 config_absent：`config_absent` 只管「没找到禁止项」，
    # 设备**根本没配 ACL** 时也会判 pass —— 那是「未配置」不是「已优化」，属误判。
    # 这里改用 config_regex + 负向先行断言：先要求存在 ACL 定义块，再声明该块内
    # 不得出现 any→any 的全通放行。两者同时成立才算 pass。
    # 负向断言必须用 (?!) 包住整个「从 ACL 起到文末」的窗口，且不能用 ^ 锚点
    # （^ 在 MULTILINE 下只匹配行首，跨行断言会失效 → 含 any→any 也会被误判 pass）。
    check=dict(
        type="config_regex",
        target="ACL 定义块",
        expect="存在 ACL 定义，且其中不含任何 any→any 全通放行条目",
        pattern=r"(?is)(?=^(?:access-list\s+\d+|acl\s+(?:number\s+)?\d+|acl\s+(?:basic|advanced)\s+\d+))"
                r"(?![\s\S]*?permit\s+(?:ip|tcp|udp|protocol)\s+any\s+any)",
    ),
    remediation=[
        "display acl 3000",
        "show access-lists",
    ],
    evidence_hint="需人工比对 ACL 命中计数（display acl / show access-lists 的 matches 列）判断"
                  "是否存在长期 0 命中的冗余规则；本条只自动判『有无全通策略』，"
                  "『规则最小化/优先级』部分需人工确认",
)

rule(
    id="DB-BND-AC-03",
    vendor="any",
    device_type="firewall",
    category="安全区域边界-访问控制",
    control_point="访问控制",
    requirement="c)应对源地址、目的地址、源端口、目的端口和协议等进行检查，以允许/拒绝数据包进出",
    weight_l3=0.7, weight_l2=0.7, weight_level=3,
    source="《等保2.0初级教材 测评操作.xlsx》sheet「安全区域边界」第8行「c)」"
           "；权重见《…权重-参考材料.xlsx》行45（二级=0.7，三级=0.7）",
    check=dict(
        type="config_regex",
        target="扩展 ACL 条目",
        expect="存在同时限定协议、源、目的与端口（五元组）的 ACL 条目",
        pattern=r"(?im)access-list\s+\d+\s+(?:permit|deny)\s+(?:tcp|udp|icmp)\s+\S+\s+\S+\s+"
                r"(?:host\s+\S+|\S+\s+\S+).*?(?:eq|gt|lt|range)\s+\d+|"
                r"rule\s+\d+\s+(?:permit|deny)\s+(?:tcp|udp|icmp)\s+source\s+\S+\s+\S+\s+"
                r"destination\s+\S+\s+\S+.*?(?:destination-port\s+eq|eq)\s+\d+",
    ),
    remediation=[
        # 原文（A 表「安全区域边界」行8 预期结果）把通配掩码写成 0.0.0.255 紧贴 IP —
        # 这是教材 OCR 把空格吃掉了，但这里**照原文收录**，不做"顺手修正"：
        # 修正后的写法在资料中找不到出处，就违反了"命令必须有出处"的硬约束。
        "access-list 101 deny tcp 172.16.4.0.0.0.0.255 172.16.3.0.0.0.0.255 eq 21",
        "rule 5 deny tcp destination 10.1.1.100 0 destination-port eq telnet",
    ],
    evidence_hint="show running-config / display current-configuration 中的 ACL 段；"
                  "只限源地址的 basic ACL（acl 2000 类）不计入本条，必须是 "
                  "access-list + 协议 + 源 + 目的 + 端口 的扩展形式。"
                  "注意教材原文的掩码粘连写法（0.0.0.255 紧贴 IP）在真机上应写为 "
                  "`172.16.4.0 0.0.0.255`",
)

rule(
    id="DB-BND-AC-04",
    vendor="any",
    device_type="firewall",
    category="安全区域边界-访问控制",
    control_point="访问控制",
    requirement="d)应能根据会话状态信息为进出数据流提供明确的允许/拒绝访问的能力",
    weight_l3=0.7, weight_l2=1, weight_level=3,
    source="《等保2.0初级教材 测评操作.xlsx》sheet「安全区域边界」第9行「d)」"
           "；权重见《…权重-参考材料.xlsx》行46（二级=1，三级=0.7）",
    check=dict(
        type="manual_confirm",
        target="防火墙状态检测能力",
        expect="设备支持并启用了状态检测（会话表），且策略基于会话状态放行/拒绝",
        pattern="",
    ),
    remediation=[
        "display current-configuration",
        "show running-config",
    ],
    evidence_hint="配置文本无法证明『是否真的按会话状态判决』。需要：①设备型号与固件的"
                  "状态检测/会话表功能说明（厂商文档）②会话表输出（如 display firewall "
                  "session table / show conn）截图 ③策略命中的会话记录。无会话表输出的设备"
                  "（纯 ACL 路由器/交换机）本项应判 not_applicable",
)

rule(
    id="DB-BND-AC-05",
    vendor="any",
    device_type="firewall",
    category="安全区域边界-访问控制",
    control_point="访问控制",
    requirement="e)应对进出网络的数据流实现基于应用协议和应用内容的访问控制",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="《等保2.0初级教材 测评操作.xlsx》sheet「安全区域边界」第10行「e)」"
           "；权重见《…权重-参考材料.xlsx》行47（二级无此项，三级=1）",
    check=dict(
        type="manual_confirm",
        target="应用层访问控制策略",
        expect="存在基于应用协议/应用内容的控制策略，并已生效",
        pattern="",
    ),
    remediation=[
        "display current-configuration",
        "show running-config",
    ],
    evidence_hint="资料（第10行预期结果）只给出『配置应用访问控制策略，对 QQ/优酷/Web/FTP 进行"
                  "管控』，没有任何可解析的命令形式，且不同厂商（下一代防火墙 / WAF）配置差异极大。"
                  "需要：①设备上应用识别/应用控制策略列表截图 ②对特定应用（如 QQ）的阻断测试"
                  "结果。纯路由交换设备本项判 not_applicable",
)

# ================================================================ 安全区域边界 / 入侵防范
rule(
    id="DB-BND-IPS-01",
    vendor="any",
    device_type="ips",
    category="安全区域边界-入侵防范",
    control_point="入侵防范",
    requirement="a)应在关键网络节点处检测、防止或限制从外部发起的网络攻击行为",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="《等保2.0初级教材 测评操作.xlsx》sheet「安全区域边界」第11行「a)」"
           "；权重见《…权重-参考材料.xlsx》行49（二级=1，三级=1）",
    check=dict(type="manual_confirm", target="边界入侵检测/防御设备", expect="存在 IPS/IDS 且规则库为近期版本，覆盖外部入口",
               pattern=""),
    remediation=["display current-configuration", "show running-config"],
    evidence_hint="需要：①设备清单与部署位置拓扑（证明在『关键网络节点』）②规则库版本与更新"
                  "时间（资料要求与测评时间较为接近）③检测到的外部攻击日志样例。"
                  "配置文本只能看到设备自身，证明不了『覆盖关键节点』",
)

rule(
    id="DB-BND-IPS-02",
    vendor="any",
    device_type="ips",
    category="安全区域边界-入侵防范",
    control_point="入侵防范",
    requirement="b)应在关键网络节点处检测、防止或限制从内部发起的网络攻击行为",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="《等保2.0初级教材 测评操作.xlsx》sheet「安全区域边界」第12行「b)」"
           "；权重见《…权重-参考材料.xlsx》行50（二级无此项，三级=1）",
    check=dict(type="manual_confirm", target="东西向入侵检测能力", expect="内网侧部署检测手段，能发现内部发起的攻击",
               pattern=""),
    remediation=["display current-configuration", "show running-config"],
    evidence_hint="需要：①内网横向流量的镜像/探针部署说明 ②内部发起攻击的检测日志。"
                  "资料（第12行预期结果）与第11行文本几乎相同，判定时应以『是否存在内部侧检测"
                  "点位』区分，不能仅凭设备型号判 pass",
)

rule(
    id="DB-BND-IPS-03",
    vendor="any",
    device_type="ips",
    category="安全区域边界-入侵防范",
    control_point="入侵防范",
    requirement="c)应在关键网络节点处检测、防止或限制从内部发起的网络攻击行为",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="《等保2.0初级教材 测评操作.xlsx》sheet「安全区域边界」第13行「c)」（原文与第12行重复）"
           "；权重见《…权重-参考材料.xlsx》行51（二级无此项，三级=1）",
    check=dict(type="manual_confirm", target="内部攻击检测与规则覆盖", expect="检测规则/策略覆盖关键节点地址范围",
               pattern=""),
    remediation=["display current-configuration", "show running-config"],
    evidence_hint="资料第13行「c)」的安全要求正文与第12行「b)」逐字相同、仅编号字母不同"
                  "（b/c），属原表笔误；此处按原表保留两条并各自独立编号，避免与资料行号"
                  "失去对应，同时便于报告按原表行号引用。判定要素同 DB-BND-IPS-02，"
                  "额外需要『规则覆盖的关键节点 IP 列表』",
)

rule(
    id="DB-BND-IPS-04",
    vendor="any",
    device_type="apt",
    category="安全区域边界-入侵防范",
    control_point="入侵防范",
    requirement="d)应采取技术措施对网络行为进行分析，实现对网络攻击特别是新型网络攻击行为的分析",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="《等保2.0初级教材 测评操作.xlsx》sheet「安全区域边界」第14行「d)」"
           "；权重见《…权重-参考材料.xlsx》行51（三级=1，行51 与 c) 共用一格权重）",
    check=dict(type="manual_confirm", target="网络行为分析/回溯系统", expect="部署回溯或抗 APT 系统，能分析未知攻击",
               pattern=""),
    remediation=["display current-configuration", "show running-config"],
    evidence_hint="需要：①网络回溯系统 / 抗 APT 系统的部署证明 ②对未知（非特征库）攻击的分析"
                  "报告样例 ③系统规则库更新时间。设备配置文本无法体现『分析能力』",
)

rule(
    id="DB-BND-IPS-05",
    vendor="any",
    device_type="ips",
    category="安全区域边界-入侵防范",
    control_point="入侵防范",
    requirement="e)当检测到攻击行为时，记录攻击源IP、攻击类型、攻击目标、攻击时间，在发生严重入侵事件时应提供报警",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="《等保2.0初级教材 测评操作.xlsx》sheet「安全区域边界」第15行「e)」"
           "；权重见《…权重-参考材料.xlsx》行52（三级=1）",
    check=dict(type="manual_confirm", target="攻击日志字段与报警配置", expect="日志含源IP/类型/目标/时间四要素，且报警已开启",
               pattern=""),
    remediation=["info-center enable", "logging on"],
    evidence_hint="需要：①攻击日志截图（需能同时看到源 IP、攻击类型、目标、时间四列）"
                  "②报警方式配置与一次实际报警记录（短信/邮件）。"
                  "「日志四要素齐全」与「报警已开启」必须分别取证",
)

# ================================================================ 安全计算环境 / 网络设备（路由器 + 交换机）
# A 表 sheet=安全计算环境：路由器段行 2~24，交换机段行 25~47
# B 表 sheet=安全计算环境-网络设备：行 2~24 对应同一批控制点
# C 表 sheet=安全通用要求权重表：行 60~82

_SHOW = {  # 各厂商「看配置」命令，来源：knowledge/command_templates.csv 系统管理类
    "Huawei": "display current-configuration",
    "H3C": "display current-configuration",
    "Cisco": "show running-config",
}


def net_rule(**kw):
    """网络设备类规则：默认 vendor=any、device_type=network_device，补 show 命令出处。"""
    kw.setdefault("vendor", "any")
    kw.setdefault("device_type", "network_device")
    kw.setdefault("category", "安全计算环境-网络设备")
    rule(**kw)


net_rule(
    id="DB-NET-ID-01", control_point="身份鉴别",
    requirement="a)应对登录的用户进行身份标识和鉴别，身份标识具有唯一性，身份鉴别信息具有复杂度要求并定期更换",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行2（路由器）/行25（交换机）；"
           "整改建议见 B 表 sheet「安全计算环境-网络设备」行2；权重见 C 表行60（二/三级均=1）",
    check=dict(type="config_regex", target="local-user / username 条目",
               expect="存在本地用户或 AAA 认证配置，且不存在空口令用户",
               pattern=r"(?im)^\s*(?:local-user\s+\S+\s+(?:password|service-type)|"
                       r"username\s+\S+\s+(?:privilege|password|secret|privilege\s+\d+\s+secret)|"
                       r"aaa\s*$|authentication-mode\s+(?:aaa|scheme)|hwtacacs\s+scheme)"),
    remediation=["local-user netadmin password irreversible-cipher Huawei@123",
                 "username admin privilege 15 secret Admin@123",
                 "aaa", "aaa new-model"],
    evidence_hint="复杂度与定期更换无法从配置判定（需人工/访谈）："
                  "B 表行2 整改建议要求『口令至少8位，由数字、字母或特殊字符中2种方式组成』。"
                  "本条只自动判『有无用户体系 + 有无空口令』；复杂度、更换周期需访谈记录",
)
net_rule(
    id="DB-NET-ID-02", control_point="身份鉴别",
    requirement="b)应具有登录失败处理功能，应配置并启用结束会话、限制非法登录次数和当登录连接超时自动退出等相关措施",
    weight_l3=0.7, weight_l2=0.7, weight_level=3,
    source="A 表 sheet「安全计算环境」行3/行26；B 表行3；C 表行61（二/三级均=0.7）",
    check=dict(type="config_regex", target="VTY / 用户界面",
               expect="VTY 下配置了超时自动退出，或存在登录失败锁定策略",
               pattern=r"(?im)^\s*(?:idle-timeout\s+\d+|exec-timeout\s+\d+|"
                       r"password-control\s+login-attempt\s+\d+\s+exceed\s+locktime\s+\d+)"),
    remediation=["idle-timeout 5", "idle-timeout 20", "user-interface vty 0 4", "line vty 0 4"],
    evidence_hint="B 表行3 要求『登录失败5次锁定账号登录15分钟』。`idle-timeout`/`exec-timeout` "
                  "证明超时退出；锁定次数需 password-control 配置或堡垒机侧策略，两条都要看。"
                  "教材 A 表行3/行26 的 Cisco 写法被 OCR 成 `exec-timcout 20`（原文如此），"
                  "真机上为 `exec-timeout 20`",
)
net_rule(
    id="DB-NET-ID-03", control_point="身份鉴别",
    requirement="c)当进行远程管理时，应采取必要措施防止鉴别信息在网络传输过程中被窃听",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行4/行27；B 表行4（权重列标『关键』）；C 表行62（二/三级均=1）",
    check=dict(type="config_regex", target="VTY inbound 协议",
               expect="VTY 只允许 SSH（protocol inbound ssh / transport input ssh）",
               pattern=r"(?im)^\s*(?:protocol\s+inbound\s+ssh|transport\s+input\s+ssh|"
                       r"stelnet\s+server\s+enable|ssh\s+server\s+enable|ip\s+ssh\s+version\s+2?)"),
    remediation=["stelnet server enable", "protocol inbound ssh", "transport input ssh",
                 "ssh server enable", "ip ssh version 2"],
    evidence_hint="需同时确认没有 `protocol inbound all`/`transport input telnet` 残留，"
                  "否则 SSH 已开但 Telnet 仍可用，应判不符合",
)
net_rule(
    id="DB-NET-ID-04", control_point="身份鉴别",
    requirement="d)应采用口令、密码技术、生物技术等两种或两种以上组合的鉴别技术对用户进行身份鉴别，且其中一种鉴别技术至少应使用密码技术来实现",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="A 表 sheet「安全计算环境」行5/行28；B 表行5（标『关键』）；C 表行63（三级=1，二级无此项）",
    check=dict(type="manual_confirm", target="双因子鉴别", expect="口令之外存在一种使用密码技术的鉴别方式",
               pattern=""),
    remediation=["aaa", "radius-server template rd1"],
    evidence_hint="A 表行5 预期结果：『除口令之外，采用了另外一种鉴别机制，此机制采用了密码技术，"
                  "如调用了密码机或采取SM1-SM4等算法』。需要：①令牌/证书/USBKey 的部署证明 "
                  "②密码算法说明。配置里出现 `radius-server` 不等于有双因子，不能据此判 pass",
)
net_rule(
    id="DB-NET-AC-01", control_point="访问控制",
    requirement="a)应对登录的用户分配账户和权限",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行6/行29；B 表行6；C 表行64（二/三级均=1）",
    check=dict(type="config_regex", target="多账户与权限分级",
               expect="存在 ≥2 个账户且各自带权限级别/角色",
               pattern=r"(?im)^\s*(?:local-user\s+\S+\s+privilege\s+level\s+\d+|"
                       r"username\s+\S+\s+privilege\s+\d+|"
                       r"authorization-attribute\s+user-role\s+\S+)"),
    remediation=["local-user admin privilege level 15",
                 "username admin privilege 15 secret Admin@123",
                 "authorization-attribute user-role network-admin"],
    evidence_hint="B 表行6 要求『设置多个帐号权限，并进行权限划分』。需人工确认："
                  "账户数量与岗位是否一一对应（多账户但全 15 级不算符合）",
)
net_rule(
    id="DB-NET-AC-02", control_point="访问控制",
    requirement="b)应重命名或删除默认账户，修改默认账户的默认口令",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行7/行30；B 表行7；C 表行65（二/三级均=1）",
    check=dict(type="manual_confirm", target="默认账户处理",
               expect="不存在 admin/huawei、cisco/cisco 等默认账户与默认口令",
               pattern=""),
    remediation=["local-user admin password irreversible-cipher Huawei@123",
                 "display current-configuration"],
    evidence_hint="A 表行7/行30 给的是『用默认账户默认口令尝试登录』这一测试动作，"
                  "不是配置检查：默认账户被改名后，配置里看到的新名字无法反证『原来那个已删』。"
                  "需要：①默认口令登录失败截图 ②账户清单。资料明确点名要查 "
                  "cisco/cisco、admin/huawei、admin@huawei.com",
)
net_rule(
    id="DB-NET-AC-03", control_point="访问控制",
    requirement="c)应及时删除或停用多余的、过期的账户，避免共享账户的存在",
    weight_l3=0.7, weight_l2=0.7, weight_level=3,
    source="A 表 sheet「安全计算环境」行8/行31；B 表行8；C 表行66（二/三级均=0.7）",
    check=dict(type="manual_confirm", target="账户清单时效性",
               expect="无多余/过期账户，管理员与账户一一对应",
               pattern=""),
    remediation=["display current-configuration", "show running-config"],
    evidence_hint="『多余/过期/共享』是业务属性，配置文本只列出账户不列出使用人。"
                  "需要：①账户与责任人对应表 ②离职人员清理记录",
)
net_rule(
    id="DB-NET-AC-04", control_point="访问控制",
    requirement="d)应授予管理用户所需的最小权限，实现管理用户的权限分离",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行9/行32；B 表行9（权重标『一般』）；C 表行67（二/三级均=1）",
    check=dict(type="config_regex", target="角色/权限分离",
               expect="存在三类角色划分（系统/安全/审计管理员）或分级权限账户",
               pattern=r"(?im)^\s*(?:local-user\s+\S+\s+(?:privilege|service-type)|"
                       r"username\s+\S+\s+privilege\s+\d+|"
                       r"authorization-attribute\s+user-role\s+\S+)"),
    remediation=["local-user admin privilege level 15",
                 "authorization-attribute user-role network-admin"],
    evidence_hint="B 表行9 要求权限分三类（系统/安全/审计）。自动检查只能证明『有分级』；"
                  "『是否真的分离、是否最小』需要账户-角色对照表 + 访谈",
)
net_rule(
    id="DB-NET-AC-05", control_point="访问控制",
    requirement="e)应由授权主体配置访问控制策略，访问控制策略规定主体对客体的访问规则",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="A 表 sheet「安全计算环境」行10/行33（原文即『此项不适合』）；B 表行10；C 表行68（三级=1）",
    check=dict(type="manual_confirm", target="不适用判定", expect="网络设备无多主体访问客体场景",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行10 原文明写『此项不适合，条款主要针对主机和数据库的测评，网络设备主要"
                  "用户为运维管理人员，无其他用户』；B 表行10 整改建议同为『此项不适用』。"
                  "本项对网络设备的结论应为 not_applicable，需保留原文出处作为依据",
)
net_rule(
    id="DB-NET-AC-06", control_point="访问控制",
    requirement="f)访问控制的粒度应达到主体为用户级或进程级，客体为文件、数据库表级",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="A 表 sheet「安全计算环境」行11/行34（原文即『此项不适合』）；B 表行11；C 表行69（三级=1）",
    check=dict(type="manual_confirm", target="不适用判定", expect="网络设备不涉及文件/数据库表级客体控制",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="同 DB-NET-AC-05：A 表行11 与 B 表行11 均写明不适用。结论应为 not_applicable",
)
net_rule(
    id="DB-NET-AC-07", control_point="访问控制",
    requirement="g)应对重要主体和客体设置安全标记，并控制主体对有安全标记信息资源的访问",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="A 表 sheet「安全计算环境」行12/行35（原文即『此项不适合』）；B 表行12；C 表行70（三级=1）",
    check=dict(type="manual_confirm", target="不适用判定", expect="网络设备一般不实现强制访问控制标记",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行12 原文『此项不适合』。若非涉密强制保护场景，结论应为 not_applicable；"
                  "若系统确有强访要求，则需厂商提供安全标记能力证明",
)
net_rule(
    id="DB-NET-AUD-01", control_point="安全审计",
    requirement="a)应启用安全审计功能，审计覆盖到每个用户，对重要的用户行为和重要安全事件进行审计",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行13/行36；B 表行13（附『是否有开审计』核查点）；C 表行71（二/三级均=1）",
    check=dict(type="config_regex", target="日志/审计开关",
               expect="已启用日志并向日志服务器输出（info-center / logging）",
               pattern=r"(?im)^\s*(?:info-center\s+enable|logging\s+on|"
                       r"info-center\s+loghost\s+\S+|logging\s+\d{1,3}(?:\.\d{1,3}){3}|"
                       r"snmp-agent\s+trap\s+enable)"),
    remediation=["info-center enable", "info-center loghost 192.10.12.1 facility local 1",
                 "logging on", "logging trap debugging", "snmp-agent"],
    evidence_hint="B 表行13 的核查点写『是否有开审计』，并另有一条要求『审计记录连续保存180天』。"
                  "本条只判开关；180 天留存需日志服务器侧取证（见 DB-NET-AUD-03）",
)
net_rule(
    id="DB-NET-AUD-02", control_point="安全审计",
    requirement="b)审计记录应包括事件的日期和时间、用户、事件类型、事件是否成功及其他与审计相关的信息",
    weight_l3=0.7, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行14/行37；B 表行14（附『审计格式』核查点）；C 表行72（二级=1，三级=0.7）",
    check=dict(type="config_regex", target="时间戳格式",
               expect="日志时间戳带日期时间（便于四要素齐全）",
               pattern=r"(?im)^\s*(?:service\s+timestamps\s+log\s+datetime|"
                       r"info-center\s+timestamp\s+\S+\s+\S+|clock\s+timezone\s+\S+)"),
    remediation=["info-center enable", "logging on"],
    evidence_hint="四要素齐全必须看实际日志样本，配置只能证明『时间戳带日期时间』。"
                  "需要：①一条真实日志截图，指出日期/时间、用户、事件类型、成功与否四列",
)
net_rule(
    id="DB-NET-AUD-03", control_point="安全审计",
    requirement="c)应对审计记录进行保护，定期备份，避免受到未预期的删除、修改或覆盖等",
    weight_l3=0.7, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行15/行38；B 表行15；C 表行73（二级=1，三级=0.7）",
    check=dict(type="config_regex", target="日志外发/备份",
               expect="日志外发到独立日志服务器（而非仅本地缓存）",
               pattern=r"(?im)^\s*(?:info-center\s+loghost\s+\S+|logging\s+\d{1,3}(?:\.\d{1,3}){3})"),
    remediation=["info-center loghost 192.10.12.1 facility local 1", "logging x.x.x.x"],
    evidence_hint="A 表行15 预期结果：『日志服务器上可查看到半年前的审计记录』。"
                  "配置只能证明已外发。需要：①日志服务器上该设备半年前的日志截图（关键证据）"
                  "②备份策略说明。无日志服务器 → 直接不符合",
)
net_rule(
    id="DB-NET-AUD-04", control_point="安全审计",
    requirement="d)应对审计进程进行保护，防止未经授权的中断",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="A 表 sheet「安全计算环境」行16/行39；B 表行16（附『只有审计管理员可以关闭审计进程』）；C 表行74（三级=1）",
    check=dict(type="manual_confirm", target="审计进程保护", expect="非审计管理员账户无法关闭审计进程",
               pattern=""),
    remediation=["local-user admin privilege level 15", "display current-configuration"],
    evidence_hint="A 表行16 的测评方法是『测试通过非审计员的其他账户来中断审计进程』——"
                  "这是操作测试不是配置读取。需要：①用非审计账户尝试 `undo info-center enable` "
                  "被拒的截图 ②账户权限表",
)
net_rule(
    id="DB-NET-IPS-01", control_point="入侵防范",
    requirement="a)应遵循最小安装的原则，仅安装需要的组件和应用程序",
    weight_l3=0.7, weight_l2=0.7, weight_level=3,
    source="A 表 sheet「安全计算环境」行17/行40（原文即『此项不适合』）；B 表行17；C 表行75（二/三级均=0.7）",
    check=dict(type="manual_confirm", target="不适用判定", expect="网络设备无『安装组件』概念",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行17 原文『此项不适合，该项要求一般在服务器上实现』；B 表行17 整改建议"
                  "同为『此项不适用』。结论应为 not_applicable",
)
net_rule(
    id="DB-NET-IPS-02", control_point="入侵防范",
    requirement="b)应关闭不需要的系统服务、默认共享和高危端口",
    weight_l3=0.7, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行18/行41；B 表行18（整改含 interface/shtudown）；"
           "C 表行76（二级=1，三级=0.7）",
    check=dict(type="config_regex", target="高危服务与空闲端口",
               expect="HTTP/未用端口已关闭，且未启用 telnet 等明文服务",
               pattern=r"(?im)^\s*(?:undo\s+http\s+server|undo\s+http\s+secure-server|"
                       r"shutdown\s*$|undo\s+telnet\s+server|no\s+ip\s+http\s+server|"
                       r"no\s+cdp\s+run|no\s+ip\s+finger|no\s+service\s+tcp-small-servers)"),
    remediation=["shutdown", "interface GigabitEthernet0/0/1", "p http shutdown",
                 "no cdp run", "no ip finger", "no ip domain-lookup"],
    evidence_hint="B 表行18 原文整改：『网络设备关闭多余未使用端口 interface 接口 / shtudown"
                  "（原文拼写有误，实为 shutdown）禁用telnet服务』，并给出核查手段『nmap扫一下』。"
                  "两条证据缺一不可：配置里的 shutdown + 端口扫描结果",
)
net_rule(
    id="DB-NET-IPS-03", control_point="入侵防范",
    requirement="c)应通过设定终端接入方式或网络地址范围对通过网络进行管理的管理终端进行限制",
    weight_l3=0.7, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行19/行42；B 表行19；C 表行77（二级=1，三级=0.7）",
    check=dict(type="config_regex", target="VTY 源地址限制",
               expect="VTY 下绑定了 ACL 限定管理源地址",
               pattern=r"(?im)^\s*(?:acl\s+\d+\s+inbound|access-class\s+\d+\s+in|"
                       r"ip\s+http\s+access-class\s+\d+|acl\s+\d{4})"),
    remediation=["acl 2000", "rule 10 permit source 10.1.100.0 0.0.0.255",
                 "user-interface vty 0 4", "line vty 0 4", "access-class 3 in"],
    evidence_hint="A 表行19 预期结果同时给了堡垒机方案与设备 ACL 方案。"
                  "若走堡垒机，则需要『堡垒机限址策略截图』，设备侧 ACL 可缺；"
                  "否则必须看到 VTY 下 acl inbound / access-class in",
)
net_rule(
    id="DB-NET-IPS-04", control_point="入侵防范",
    requirement="d)应提供数据有效性检验功能，保证通过人机接口输入或通过通信接口输入的内容符合系统设定要求",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行20/行43（原文即『此项不适合』）；B 表行20；C 表行78（二/三级均=1）",
    check=dict(type="manual_confirm", target="不适用判定", expect="该项属应用层要求",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行20 原文『此项不适合，该项要求一般在应用层面上核查』。"
                  "对网络设备结论应为 not_applicable",
)
net_rule(
    id="DB-NET-IPS-05", control_point="入侵防范",
    requirement="e)应能发现可能存在的已知漏洞，并在经过充分测试评估后，及时修补漏洞",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行21/行44；B 表行21；C 表行79（二/三级均=1）",
    check=dict(type="manual_confirm", target="漏洞发现与修补", expect="有漏洞扫描记录与补丁升级记录",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行21 测评方法即『应进行漏洞扫描，核查是否不存在高风险漏洞』。"
                  "需要：①最近一次漏洞扫描报告（含设备 IP）②固件版本与厂商公告的比对说明 "
                  "③修补/缓解措施记录。配置文本无法体现",
)
net_rule(
    id="DB-NET-IPS-06", control_point="入侵防范",
    requirement="f)应能够检测到对重要节点进行入侵的行为，并在发生严重入侵事件时提供报警",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="A 表 sheet「安全计算环境」行22/行45（原文即『此项不适合』）；B 表行22；C 表行80（三级=1）",
    check=dict(type="manual_confirm", target="不适用判定/转由 IPS 覆盖", expect="该项一般在入侵防护系统上实现",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行22 原文『此项不适合，该项要求一般在入侵防护系统上实现』。"
                  "对网络设备本身结论为 not_applicable，但应在报告中注明由边界 IPS 项"
                  "（DB-BND-IPS-01）承接",
)
net_rule(
    id="DB-NET-MAL-01", control_point="恶意代码防范",
    requirement="应采用免受恶意代码攻击的技术措施或主动免疫可信验证机制及时识别入侵和病毒行为，并将其有效阻断",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行23/行46（原文即『此项不适合』）；B 表行23；C 表行81（二/三级均=1）",
    check=dict(type="manual_confirm", target="不适用判定", expect="该项一般在服务器上实现",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行23 原文『此项不适合，该项要求一般在服务器上实现』。"
                  "注意 C 表行81 三级要求文本与二级不同（三级为『主动免疫可信验证机制』），"
                  "但 A 表测评方法对设备统一判不适用，故结论仍为 not_applicable，"
                  "需在报告中说明三级文本差异",
)
net_rule(
    id="DB-NET-TRUST-01", control_point="可信验证",
    requirement="可基于可信根对计算设备的系统引导程序、系统程序、重要配置参数和应用程序等进行可信验证，"
                "并在应用程序的关键执行环节进行动态可信验证，在检测到其可信性受到破坏后进行报警，"
                "并将验证结果形成审计记录送至安全管理中心",
    weight_l3=0.4, weight_l2=0.4, weight_level=3,
    source="A 表 sheet「安全计算环境」行24/行47（测评方法『参见2.3和3.6可信验证』）；B 表行24；C 表行82（二/三级均=0.4）",
    check=dict(type="manual_confirm", target="可信根硬件", expect="设备具备可信根芯片并启用可信验证",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表本身没有给出测评方法（只写『参见2.3和3.6可信验证』），属资料缺口。"
                  "需要：①设备是否具备 TPM/TPCM 可信根的硬件说明 ②安全管理中心接收验证结果的"
                  "日志截图。无可信根 → 不符合（本项是『可』字增强项，通常不计入不符合项扣分）",
)

# ================================================================ 安全计算环境 / 安全设备（防火墙）
# A 表 sheet=安全计算环境 行 48~70；B 表 sheet=安全计算环境-安全设备 行 2~24

def fw_rule(**kw):
    kw.setdefault("vendor", "any")
    kw.setdefault("device_type", "firewall")
    kw.setdefault("category", "安全计算环境-安全设备")
    rule(**kw)


fw_rule(
    id="DB-FW-ID-01", control_point="身份鉴别",
    requirement="a)应对登录的用户进行身份标识和鉴别，身份标识具有唯一性，身份鉴别信息具有复杂度要求并定期更换",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行48（以天融信防火墙 WEB/Console 为例，"
           "预期结果明写『口令长度8位以上…每季度至少更改一次』）；"
           "整改建议见 B 表 sheet「安全计算环境-安全设备」行2；权重见 C 表行60",
    check=dict(type="manual_confirm", target="管理员账户与口令策略",
               expect="账户唯一、无空口令；口令≥8位且两类字符、每季度更换",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行48 的测评路径是 WEB 界面（用户认证>>用户管理）与 Console 登录，"
                  "资料未给出任何 CLI 命令，故不能写成 config_* 检查。"
                  "需要：①用户列表截图（证明唯一、无空口令）②口令策略配置页截图 "
                  "③最近一次口令更换记录（每季度）",
)
fw_rule(
    id="DB-FW-ID-02", control_point="身份鉴别",
    requirement="b)应具有登录失败处理功能，应配置并启用结束会话、限制非法登录次数和当登录连接超时自动退出等相关措施",
    weight_l3=0.7, weight_l2=0.7, weight_level=3,
    source="A 表 sheet「安全计算环境」行49（系统管理>>配置>>系统参数>>高级属性：最大登录失败次数、远程登录连接超时）；"
           "B 表行3；C 表行61",
    check=dict(type="manual_confirm", target="登录失败与超时参数",
               expect="已配置最大登录失败次数与远程登录超时",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行49 明确给出 WEB 路径：系统管理>>配置>>『系统参数』>>『高级属性』，"
                  "可见『最大登录失败次数』与『远程登录连接超时』两栏。"
                  "需要：①该页面截图（两个参数都要可见）②策略已生效的验证（连续失败锁定测试）",
)
fw_rule(
    id="DB-FW-ID-03", control_point="身份鉴别",
    requirement="c)当进行远程管理时，应采取必要措施防止鉴别信息在网络传输过程中被窃听",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行50（WEB 管理须经 SSL 加密）；B 表行4（标『关键』）；C 表行62",
    check=dict(type="manual_confirm", target="WEB 管理加密",
               expect="WEB 管理通过 HTTPS/SSL；未开放明文 HTTP/Telnet",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行50 预期结果：『通过WEB界面进行远程管理时，通过SSL协议进行加密处理』。"
                  "需要：①管理 URL 为 https 的截图（含证书信息）②开放服务页中 telnet/http "
                  "已关闭的截图（A 表行65 提到『开放服务』页签）",
)
fw_rule(
    id="DB-FW-ID-04", control_point="身份鉴别",
    requirement="d)应采用口令、密码技术、生物技术等两种或两种以上组合的鉴别技术对用户进行身份鉴别，且其中一种鉴别技术至少应使用密码技术来实现",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="A 表 sheet「安全计算环境」行51（用户认证>>用户管理，认证方式须为『本地口令+证书认证』或『外部口令+证书认证』）；"
           "B 表行5（标『关键』）；C 表行63（三级=1）",
    check=dict(type="manual_confirm", target="双因子认证方式",
               expect="用户认证方式为『本地口令+证书认证』或『外部口令+证书认证』",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行51 给出可判定的字面值：认证方式必须等于『本地口令+证书认证』或"
                  "『外部口令+证书认证』。需要：①用户属性页『认证方式』字段截图 "
                  "②证书颁发与部署说明",
)
fw_rule(
    id="DB-FW-AC-01", control_point="访问控制",
    requirement="a)应对登录的用户分配账户和权限",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行52（用户认证>>用户管理，账户权限须与职位对应）；B 表行6；C 表行64",
    check=dict(type="manual_confirm", target="账户与权限分配",
               expect="各账户权限与其职责对应，账户管理员/配置管理员不具审计员权限",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行52 明确判据：『账户管理员和配置管理员不应具有审计员权限』。"
                  "需要：①用户列表及各自权限截图 ②职责对照表。"
                  "配置文本无法区分角色语义",
)
fw_rule(
    id="DB-FW-AC-02", control_point="访问控制",
    requirement="b)应重命名或删除默认账户，修改默认账户的默认口令",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行53；B 表行7；C 表行65",
    check=dict(type="manual_confirm", target="默认账户处理",
               expect="默认账户已重命名/删除，默认口令已修改",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="需要：①用户列表中不含厂商默认账户名（如天融信的默认管理账户）的截图 "
                  "②默认口令登录失败的测试结果。资料未点名具体默认账户名，"
                  "需按实际厂商文档补全",
)
fw_rule(
    id="DB-FW-AC-03", control_point="访问控制",
    requirement="c)应及时删除或停用多余的、过期的账户，避免共享账户的存在",
    weight_l3=0.7, weight_l2=0.7, weight_level=3,
    source="A 表 sheet「安全计算环境」行54；B 表行8；C 表行66",
    check=dict(type="manual_confirm", target="账户清单时效性",
               expect="无多余/过期账户，无共享账户",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="需要：①防火墙用户账户列表 ②账户用途说明（证明一一对应）"
                  "③已停用账户的状态截图（若无法删除）",
)
fw_rule(
    id="DB-FW-AC-04", control_point="访问控制",
    requirement="d)应授予管理用户所需的最小权限，实现管理用户的权限分离",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行55（账户分系统管理员/安全管理员/审计管理员三类）；B 表行9（标『一般』）；C 表行67",
    check=dict(type="manual_confirm", target="角色划分与权限分离",
               expect="存在系统/安全/审计三类角色，且禁止兼任配置与审计",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行55 给出判据：『禁止对管理用户同时赋予配置管理员和审计管理员权限』。"
                  "需要：①角色清单截图 ②任一用户的权限明细，证明无『配置+审计』兼任",
)
fw_rule(
    id="DB-FW-AC-05", control_point="访问控制",
    requirement="e)应由授权主体配置访问控制策略，访问控制策略规定主体对客体的访问规则",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="A 表 sheet「安全计算环境」行56（原文即『此项不适合』）；B 表行10；C 表行68（三级=1）",
    check=dict(type="manual_confirm", target="不适用判定", expect="条款针对主机和数据库", pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行56 与 B 表行10 均写『此项不适合，条款主要针对主机和数据库的测评』。"
                  "结论应为 not_applicable",
)
fw_rule(
    id="DB-FW-AC-06", control_point="访问控制",
    requirement="f)访问控制的粒度应达到主体为用户级或进程级，客体为文件、数据库表级",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="A 表 sheet「安全计算环境」行57（原文即『此项不适合』）；B 表行11；C 表行69（三级=1）",
    check=dict(type="manual_confirm", target="不适用判定", expect="条款针对主机和数据库", pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行57 测评方法与预期结果均写『此项不适合，条款主要针对主机和数据库的测评，"
                  "网络设备主要用户为运维管理人员，无其他用户』；B 表行11 整改建议同为『此项不适用』。"
                  "结论应为 not_applicable，并保留该原文出处作为判定依据",
)
fw_rule(
    id="DB-FW-AC-07", control_point="访问控制",
    requirement="g)应对重要主体和客体设置安全标记，并控制主体对有安全标记信息资源的访问",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="A 表 sheet「安全计算环境」行58（原文即『此项不适合，该项要求一般在服务器上实现』）；B 表行12；C 表行70（三级=1）",
    check=dict(type="manual_confirm", target="不适用判定", expect="防火墙无安全标记语义", pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行58 测评方法与预期结果均写『此项不适合，该项要求一般在服务器上实现』；"
                  "B 表行12 整改建议同为『此项不适用』。非涉密强制访问控制场景下结论应为 "
                  "not_applicable；若系统确有强访要求，需厂商出具安全标记能力证明",
)
fw_rule(
    id="DB-FW-AUD-01", control_point="安全审计",
    requirement="a)应启用安全审计功能，审计覆盖到每个用户，对重要的用户行为和重要安全事件进行审计",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行59（日志与报警>>日志设置，须配服务器地址/端口/级别/类型）；B 表行13；C 表行71",
    check=dict(type="config_regex", target="日志服务器地址",
               expect="配置中已指定日志服务器地址（厂商 CLI 可见时）",
               pattern=r"(?im)^\s*(?:logging\s+(?:host\s+)?\d{1,3}(?:\.\d{1,3}){3}|"
                       r"log\s+host\s+\d{1,3}(?:\.\d{1,3}){3}|"
                       r"loghost\s+\d{1,3}(?:\.\d{1,3}){3}|"
                       r"syslog\s+server\s+\d{1,3}(?:\.\d{1,3}){3})"),
    remediation=["display current-configuration"],
    evidence_hint="两级判定：①若厂商 CLI 可见（如 logging host / syslog server），配置里"
                  "必须出现日志服务器 IP —— 没有 IP 可直接判不符合；②A 表行59 给的是 WEB 路径"
                  "（日志与报警>>日志设置），四个必配字段（服务器地址、端口、级别、类型）"
                  "仍需该页截图核对；③日志服务器侧收到该防火墙日志的截图。"
                  "仅有配置地址、但服务器侧收不到，仍判不符合",
)
fw_rule(
    id="DB-FW-AUD-02", control_point="安全审计",
    requirement="b)审计记录应包括事件的日期和时间、用户、事件类型、事件是否成功及其他与审计相关的信息",
    weight_l3=0.7, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行60（日志服务器 功能>>日志查询>>审计域）；B 表行14；C 表行72（二级=1，三级=0.7）",
    check=dict(type="manual_confirm", target="审计记录字段",
               expect="日志含日期时间、用户、事件类型、成功与否",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行60 的取证位置在**日志服务器**（功能>>日志查询>>审计域），不在防火墙本身。"
                  "需要：①按防火墙 IP 过滤后的一条日志截图，指出四个字段 ②日志源列表含该防火墙 IP",
)
fw_rule(
    id="DB-FW-AUD-03", control_point="安全审计",
    requirement="c)应对审计记录进行保护，定期备份，避免受到未预期的删除、修改或覆盖等",
    weight_l3=0.7, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行61（管理策略>>任务调度策略，须存在『备份数据库任务』计划任务）；B 表行15；C 表行73",
    check=dict(type="manual_confirm", target="日志备份任务",
               expect="存在定时数据库备份任务，且能查到半年前日志",
               pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行61 给出可判定判据：任务调度策略里『存在类型为备份数据库任务的计划任务』。"
                  "需要：①任务列表截图（含类型与执行周期）②半年前日志可查的截图",
)
fw_rule(
    id="DB-FW-AUD-04", control_point="安全审计",
    requirement="d)应对审计进程进行保护，防止未经授权的中断",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="A 表 sheet「安全计算环境」行62；B 表行16；C 表行74（三级=1）",
    check=dict(type="manual_confirm", target="审计进程保护",
               expect="非审计员账户无法中断审计进程", pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行62 测评方法是『测试通过非审计员的其他账户来中断审计进程』。"
                  "需要：①非审计账户尝试关闭日志被拒的截图 ②角色权限表",
)
fw_rule(
    id="DB-FW-IPS-01", control_point="入侵防范",
    requirement="a)应遵循最小安装的原则，仅安装需要的组件和应用程序",
    weight_l3=0.7, weight_l2=0.7, weight_level=3,
    source="A 表 sheet「安全计算环境」行63（原文即『此项不适合』）；B 表行17；C 表行75",
    check=dict(type="manual_confirm", target="不适用判定", expect="该项一般在服务器上实现", pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行63 测评方法与预期结果均写『此项不适合，该项要求一般在服务器上实现』；"
                  "B 表行17 整改建议同为『此项不适用』。结论应为 not_applicable，"
                  "并在报告中保留原文出处；若该防火墙兼作服务器宿主，则需单独评审",
)
fw_rule(
    id="DB-FW-IPS-02", control_point="入侵防范",
    requirement="b)应关闭不需要的系统服务、默认共享和高危端口",
    weight_l3=0.7, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行64（原文即『此项不适合』）；B 表行18；C 表行76（二级=1，三级=0.7）",
    check=dict(type="manual_confirm", target="不适用判定", expect="该项一般在服务器上实现", pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="注意此处与网络设备不同：A 表行64 对**防火墙**判不适用，而 A 表行18/行41 对"
                  "路由器**交换机**要求关闭多余端口。不要混用。结论应为 not_applicable，"
                  "但『开放服务』中的明文 telnet/http 仍应在 DB-FW-ID-03 中核查",
)
fw_rule(
    id="DB-FW-IPS-03", control_point="入侵防范",
    requirement="c)应通过设定终端接入方式或网络地址范围对通过网络进行管理的管理终端进行限制",
    weight_l3=0.7, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行65（系统管理>>配置>>开放服务，webui/ssh/telnet 规则的控制地址）；B 表行19；C 表行77",
    check=dict(type="config_regex", target="管理服务绑定源地址",
               expect="管理服务（webui/ssh）绑定了受限源地址，而非 any",
               pattern=r"(?im)^\s*(?:ssh\s+server\s+acl\s+\d+|"
                       r"telnet\s+server\s+acl\s+\d+|"
                       r"http\s+server\s+acl\s+\d+|"
                       r"ip\s+http\s+access-class\s+\d+|"
                       r"access-class\s+\d+\s+in)"),
    remediation=["display current-configuration"],
    evidence_hint="两级判定：①配置层——若厂商 CLI 暴露 ssh server acl / http server acl / "
                  "access-class 之类绑定，必须看到源地址限定，配成 any 直接判不符合；"
                  "②A 表行65 的 WEB 路径（系统管理>>配置>>开放服务）中，webui/ssh/telnet 规则的"
                  "『控制地址』列必须指向具体主机/地址组资源而非 any，需该页截图；"
                  "③资源管理>>地址 页证明控制地址对应的实际 IP 段。堡垒机限址可替代设备侧 ACL",
)
fw_rule(
    id="DB-FW-IPS-04", control_point="入侵防范",
    requirement="d)应提供数据有效性检验功能，保证通过人机接口输入或通过通信接口输入的内容符合系统设定要求",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行66（原文即『此项不适合』）；B 表行20；C 表行78",
    check=dict(type="manual_confirm", target="不适用判定", expect="该项一般在应用层面上核查", pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行66 测评方法与预期结果均写『此项不适合，该项要求一般在应用层面上核查』；"
                  "B 表行20 整改建议同为『此项不适用』。结论应为 not_applicable，"
                  "并注明该项由业务应用系统侧的等保测评承接",
)
fw_rule(
    id="DB-FW-IPS-05", control_point="入侵防范",
    requirement="e)应能发现可能存在的已知漏洞，并在经过充分测试评估后，及时修补漏洞",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行67；B 表行21；C 表行79（二/三级均=1）",
    check=dict(type="manual_confirm", target="漏洞发现与修补", expect="有漏洞扫描与固件升级记录", pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="需要：①防火墙的漏洞扫描报告 ②当前固件版本与厂商最新版的比对 "
                  "③高风险漏洞的修补/缓解记录",
)
fw_rule(
    id="DB-FW-IPS-06", control_point="入侵防范",
    requirement="f)应能够检测到对重要节点进行入侵的行为，并在发生严重入侵事件时提供报警",
    weight_l3=1, weight_l2=None, weight_level=3,
    source="A 表 sheet「安全计算环境」行68（核查防火墙入侵检测功能是否启用、报警方式含短信/邮件）；B 表行22；C 表行80（三级=1）",
    check=dict(type="manual_confirm", target="入侵检测与报警",
               expect="防火墙入侵检测功能已启用，且配置了短信/邮件报警", pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="注意与路由器/交换机不同：A 表行68 对**防火墙**是**可测项**（不是不适用），"
                  "要求『启用入侵检测功能』+『短信/邮件报警』。需要：①入侵检测开关截图 "
                  "②报警方式配置与一次实际报警记录",
)
fw_rule(
    id="DB-FW-MAL-01", control_point="恶意代码防范",
    requirement="应采用免受恶意代码攻击的技术措施或主动免疫可信验证机制及时识别入侵和病毒行为，并将其有效阻断",
    weight_l3=1, weight_l2=1, weight_level=3,
    source="A 表 sheet「安全计算环境」行69（原文即『此项不适合』）；B 表行23；C 表行81（二/三级均=1）",
    check=dict(type="manual_confirm", target="不适用判定", expect="该项一般在服务器上实现", pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表行69 测评方法与预期结果均写『此项不适合，该项要求一般在服务器上实现』；"
                  "B 表行23 整改建议同为『此项不适用』。防火墙本身不承载恶意代码防范职责，"
                  "结论应为 not_applicable，该项由主机/终端侧等保测评承接",
)
fw_rule(
    id="DB-FW-TRUST-01", control_point="可信验证",
    requirement="可基于可信根对计算设备的系统引导程序、系统程序、重要配置参数和应用程序等进行可信验证，"
                "并在应用程序的关键执行环节进行动态可信验证，在检测到其可信性受到破坏后进行报警，"
                "并将验证结果形成审计记录送至安全管理中心",
    weight_l3=0.4, weight_l2=0.4, weight_level=3,
    source="A 表 sheet「安全计算环境」行70（测评方法『参见2.3和3.6可信验证』）；B 表行24；C 表行82（二/三级均=0.4）",
    check=dict(type="manual_confirm", target="可信根硬件", expect="防火墙具备可信根并启用可信验证", pattern=""),
    remediation=["display current-configuration"],
    evidence_hint="A 表无具体测评方法（资料缺口）。需要：①可信根芯片说明 ②安全管理中心收到的"
                  "验证结果日志。无可信根 → 不符合（『可』字增强项）",
)


# ---------------------------------------------------------------- 生成
def build() -> tuple[list[dict], dict]:
    idx = SourceIndex(kb_blob=_kb_blob())
    out = []
    problems = []

    for r in RULES:
        parent, seq = r["id"].rsplit("-", 1)
        eid = f"{parent}-{seq}"
        wl = r["weight_level"]
        w = r["weight_l3"] if wl == 3 else r["weight_l2"]
        if w is None:
            raise ValueError(f"{eid}: weight_level={wl} 但对应权重为空")
        logic = dict(
            id=eid,
            vendor=r["vendor"],
            device_type=r["device_type"],
            category=r["category"],
            control_point=r["control_point"],
            requirement=r["requirement"],
            weight_level=wl,
            severity=severity_of(w),
            source=r["source"],
            check=r["check"],
            remediation=r["remediation"],
            evidence_hint=r["evidence_hint"],
        )
        # 契约：check.type 只允许五种
        assert logic["check"]["type"] in {
            "config_contains", "config_absent", "config_regex",
            "config_value_compare", "manual_confirm",
        }, f"{eid}: 非法 check.type"
        # 契约：manual_confirm 必须写明需要什么证据
        if logic["check"]["type"] == "manual_confirm":
            assert len(logic["evidence_hint"]) >= 40, f"{eid}: manual_confirm 的 evidence_hint 太短"
        # 契约：remediation 必须非空，且每条命令要有出处
        assert logic["remediation"], f"{eid}: remediation 为空"
        for cmd in logic["remediation"]:
            ok, how = idx.check(cmd)
            if not ok:
                problems.append((eid, cmd, how))

        # 附加：二级权重与来源行，便于复用到二级系统
        logic["weight_detail"] = {"level2": r["weight_l2"], "level3": r["weight_l3"]}
        out.append(logic)

    # id 唯一
    ids = [x["id"] for x in out]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ValueError(f"重复 id: {sorted(dup)}")

    if problems:
        lines = "\n".join(f"  {eid}: {cmd!r} → {how}" for eid, cmd, how in problems)
        raise SystemExit(f"以下 remediation 命令在资料中找不到出处，拒绝生成：\n{lines}")

    index = {
        "generated_by": "tools/build_dengbao_rules.py",
        "source_files": [X_A.name, X_B.name, X_C.name, "knowledge/command_templates.csv"],
        "severity_rule": "由 weight_level 对应权重推导：1→high，0.7→medium，0.4→low",
        "total": len(out),
        "by_severity": {},
        "by_type": {},
        "by_category": {},
        "rules": [],
    }
    for x in out:
        index["by_severity"][x["severity"]] = index["by_severity"].get(x["severity"], 0) + 1
        t = x["check"]["type"]
        index["by_type"][t] = index["by_type"].get(t, 0) + 1
        c = x["category"]
        index["by_category"][c] = index["by_category"].get(c, 0) + 1
        index["rules"].append({
            "id": x["id"],
            "category": x["category"],
            "severity": x["severity"],
            "check_type": t,
            "file": f"{x['id']}.yaml",
        })
    index["rules"].sort(key=lambda d: d["id"])
    return out, index


def main() -> int:
    _dump_source_lines()
    rules, index = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.yaml"):
        old.unlink()

    for r in rules:
        # 字段顺序固定，保证 diff 可读
        ordered = {
            "id": r["id"],
            "vendor": r["vendor"],
            "device_type": r["device_type"],
            "category": r["category"],
            "control_point": r["control_point"],
            "requirement": r["requirement"],
            "weight_level": r["weight_level"],
            "severity": r["severity"],
            "source": r["source"],
            "check": r["check"],
            "remediation": r["remediation"],
            "evidence_hint": r["evidence_hint"],
            "weight_detail": r["weight_detail"],
        }
        (OUT_DIR / f"{r['id']}.yaml").write_text(
            yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False, width=110),
            encoding="utf-8",
        )

    (OUT_DIR / "rules_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"生成规则 {len(rules)} 条 → {OUT_DIR}")
    print(f"  severity: {index['by_severity']}")
    print(f"  check.type: {index['by_type']}")
    for k, v in sorted(index["by_category"].items()):
        print(f"    {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    raise SystemExit(main())
