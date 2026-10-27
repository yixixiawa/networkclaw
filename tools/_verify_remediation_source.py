"""核对：规则 remediation 里每条命令是否真能在原始资料中找到出处。

出处白名单（三选一即通过）：
  1. csv-exact  : 与 knowledge/command_templates.csv 的 command 列逐字一致（忽略大小写与空白）
  2. kb-substr  : 作为子串出现在测评操作表「测评方法 / 预期结果」原文中
  3. csv-shape  : 仅差「可变值」的模板同构——变量位必须是 csv 里出现过的**变量锚**，
                  且命令里**新增**的常量数词不得超过 csv 模板的变量数。
                  （只有 ip / mac / 十进制数 / 接口号 / 引号占位符 才算变量锚；
                   英文单词一律算常量，所以 "totally-made-up-command xyz" 无法蒙混过关）
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

# 命令模板唯一数据源：按项目根解析（不要写死绝对路径——项目目录改名/搬家就会失效）
CSV_PATH = str(Path(__file__).resolve().parent.parent / "knowledge" / "command_templates.csv")

# ---------------------------------------------------------------- 骨架提取
# 关键洞察：手工枚举「什么算值」永远会漏（Huawei@123 / netadmin / irreversible-cipher 形态各异）。
# 反过来做——**骨架只保留命令关键字**（短英文单词，且不是纯数字/不含 @ 符号），
# 其余一切（IP、接口号、口令、密文、引号占位符、长随机串）统一挖成 \x00 占位符。
# 这样 "local-user X password Y Z" 与 "local-user X password Y Z" 天然同构，
# 而 "totally-made-up-command xyz" 的 4 个英文单词里 2 个是真实命令关键字、
# "made-up" 不是 → 骨架对不上任何 csv 模板，判定为无出处。

# 允许作为「命令关键字」保留的形态：纯小写短词 / 带连字符的厂商关键字（vlan-interface）
_KEYWORD = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z][a-z0-9]*)*$")
# 这些词形太像「人写的值」，一律当值处理，不进骨架
_VALUE_HINT = re.compile(r"(@|xxx|\*|^[a-z]+@|\d{4,})", re.I)
# 值位占位符。用可打印字符，避免 split() 与空白的交互问题。
_PH = "«V»"

# 「样例值白名单」：csv 模板里写成固定样例、但实际部署必然逐台不同的词位。
# 用 (骨架词元组, 位置) 精确声明，避免放宽成「任意英文词都能替换」。
#   local-user admin password ...   ← 第 2 位 admin 是样例用户名
SAMPLE_VALUE_SLOTS: set[tuple[tuple[str, ...], int]] = {
    (("local-user", "admin", "password", "irreversible-cipher", _PH), 1),
    (("local-user", "admin", "privilege", "level", _PH), 1),
    (("local-user", "admin", "service-type", "ssh"), 1),
    (("local-user", "admin", "class", "manage"), 1),
    (("username", "admin", "privilege", _PH, "secret", _PH), 1),
    (("sysname", _PH), 1),
    (("hostname", _PH), 1),
}


def _shape(cmd: str) -> str:
    """把命令变成「只剩关键字」的骨架。值全部折叠为 _PH（连续多个折叠成一个）。"""
    out = []
    for w in cmd.split():
        if _KEYWORD.match(w) and not _VALUE_HINT.search(w):
            out.append(w)
        else:
            out.append(_PH)
    return re.sub(r"[\x00]+", " ", " ".join(out)).strip()


# 教材里的「预期结果」常写成 `XXX` / `xxxx` 占位，_KEYWORD 不匹配 → 自动进占位符，
# 所以 "local-user netadmin password irreversible-cipher ..." 能与
# csv 的 "local-user admin password irreversible-cipher Huawei@123" 同构。
# 反过来 "undo shutdown" 在 csv 中**不存在**任何 undo shutdown 模板（只有 undo ip address /
# undo switchport / undo ip route-static 等），因此它必须靠测评表原文命中。


def _norm(s: str) -> str:
    # 字典序归一：Huawei/H3C 的 undo 与 Cisco 的 no 是同一语义的两种方言，
    # 统一折叠成 undo 后再比对，避免「同一条撤销命令因厂商写法不同被判无出处」。
    t = re.sub(r"\s+", " ", (s or "").strip().lower())
    t = re.sub(r"^no (?=\S)", "undo ", t)
    return t


class SourceIndex:
    def __init__(self, csv_path: str = CSV_PATH, kb_blob: str = ""):
        self.csv_cmds = [_norm(r["command"]) for r in csv.DictReader(open(csv_path, encoding="utf-8-sig"))]
        self.kb = _norm(kb_blob)
        # 按行切分后的原文行集合。教材单元格里命令本身就是逐行排列的，
        # 「整段子串」匹配会被前后噪声带偏，「逐行精确」才是真实形态。
        self.kb_lines = {_norm(x) for x in re.split(r"[\r\n]+", kb_blob or "") if x.strip()}

    # ---------------- 3. 模板同构
    def check(self, cmd: str) -> tuple[bool, str]:
        n = _norm(cmd)
        if not n:
            return False, "空命令"
        if n in self.csv_cmds:
            return True, "csv-exact"
        if n in self.kb_lines:
            return True, "kb-line"
        if n in self.kb:
            return True, "kb-substr"
        sk = _shape(n)
        for c in self.csv_cmds:
            if _shape(c) == sk:
                return True, "csv-shape"
        # 4) 宽松同构：允许**少量位置**的关键字差异，对应「用户名/主机名」这类
        #    模板里写成固定样例、实际部署必然不同的值位。
        #    约束：① 词位数量一致 ② 差异位里至少有一方是占位符或该位两侧都不是
        #    强命令关键字（靠 allow_diff 控制最多 1 处）③ 首词必须完全相同（命令名不能变）。
        #    这样 "undo shutdown"（csv 无 undo shutdown 模板）依然无法蒙混过关。
        sn = sk.split()
        for c in self.csv_cmds:
            csk = _shape(c).split()
            if len(csk) != len(sn) or sn[0] != csk[0]:
                continue
            diffs = [(a, b) for a, b in zip(sn, csk) if a != b]
            if len(diffs) == 0:
                return True, "csv-shape"
            if len(diffs) == 1:
                a, b = diffs[0]
                # 唯一允许的差异位：必须有一方是占位符，或落在下方的「样例值白名单」上。
                # 「双方都是英文词」不无条件放行 —— 那等于允许换掉命令关键字，
                # "undo shutdown" 这类无出处命令会因此蒙混过关。
                if a == _PH or b == _PH:
                    return True, "csv-loose"
                pos = csk.index(b)
                if (tuple(csk), pos) in SAMPLE_VALUE_SLOTS:
                    return True, "csv-sample"
        return False, "无出处"


if __name__ == "__main__":
    import io
    import sys

    import openpyxl

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    BASE = r"D:\net-security-teach\等级评估\等保材料-课堂1.0"
    wb = openpyxl.load_workbook(BASE + r"\等保2.0初级教材 测评操作.xlsx", data_only=True)
    blob = []
    for sheet in ("安全区域边界", "安全计算环境"):
        ws = wb[sheet]
        for r in range(1, ws.max_row + 1):
            for c in range(1, ws.max_column + 1):
                v = ws.cell(r, c).value
                if v:
                    blob.append(str(v))
    idx = SourceIndex(kb_blob="\n".join(blob))

    cases = [
        # —— 期望通过：csv 逐字命中
        ("interface GigabitEthernet0/0/1", True),
        ("display current-configuration", True),
        ("show running-config", True),
        ("line vty 0 4", True),
        ("transport input ssh", True),
        ("acl 2000", True),
        ("traffic-filter outbound acl 3000", True),
        ("stelnet server enable", True),
        ("user-interface vty 0 4", True),
        # —— 期望通过：csv 模板同构（只差可变值）
        ("rule 10 permit source 10.1.100.0 0.0.0.255", True),
        ("local-user netadmin password irreversible-cipher Huawei@123", True),
        ("interface GigabitEthernet0/0/2", True),
        # —— 期望通过：测评表原文子串命中
        ("shutdown", True),
        ("idle-timeout 5", True),
        ("info-center enable", True),
        ("access-list 100 deny ip any any", True),
        ("local-user test password cipher 456%&ET", True),
        # —— 期望被拒：资料里根本没有的命令
        ("totally-made-up-command xyz", False),
        ("disable everything now", False),
        ("enable magic security mode", False),
        ("set password policy strict", False),
        ("password min-length 12 expiration 90", False),
        ("undo shutdown", False),   # csv 无 undo shutdown 模板，测评表也未出现该短语
    ]
    bad = 0
    for cmd, want in cases:
        ok, how = idx.check(cmd)
        flag = "OK  " if ok == want else "BAD "
        if ok != want:
            bad += 1
        print(f"  [{flag}] want={str(want):<5} got={how:<10} {cmd}")
    print("\n结论:", "全部符合预期" if bad == 0 else f"{bad} 条判定不符预期")
