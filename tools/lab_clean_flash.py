"""把实验包里设备的预置配置清成空白，让模型真正"从零配置"。

为什么要做这件事
----------------
eNSP 实验包在 `paper/<设备UUID>/flash.efz` 里塞了一份完整的 `vrpcfg.cfg`，
那就是**参考答案本体**（sysname + vlan batch + 所有接口配置都齐了）。
设备一开机就自动加载它，于是模型什么都不做也能"验收 100%"——
实测实验 01 的 hit_before=23 / net=+0，纯属假阳性。

清洗后设备起来是空配置，模型必须自己配，net（净提升）才成为真实指标。

文件格式
--------
flash.efz = eNSP 私有头（长度不固定，实测 4860 字节）+ 标准 ZIP。
ZIP 里只有一个成员 `vrpcfg.cfg`（GBK/UTF-8 混合的华为配置文本）。
改完按「原头 + 新 ZIP」拼回去即可，eNSP 能正常识别。

用法
----
    python tools/lab_clean_flash.py --dry-run              # 只看会改哪些
    python tools/lab_clean_flash.py                        # 清洗全部实验
    python tools/lab_clean_flash.py --only 01,02           # 只清洗指定编号
    python tools/lab_clean_flash.py --restore              # 还原（用 .orig 备份）

清洗策略：保留 sysname 与设备默认段，丢掉 vlan / 接口 / 路由 / STP 等
一切"题目要你配的东西"，让接口回到出厂默认状态。
"""
from __future__ import annotations

import argparse
import io
import re
import shutil
import sys
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

SRC_DIR = BASE_DIR / "data" / "ensp_labs" / "src"
DOC_DIR = BASE_DIR / "knowledge" / "experiments"

# 这些段是设备出厂自带的骨架，跟题目无关，留着能减少无关报错
KEEP_PAT = re.compile(
    r"^\s*(sysname|undo info-center enable|cluster enable|ntdp enable|ndp enable"
    r"|drop illegal-mac alarm|diffserv domain default|drop-profile default"
    r"|aaa|authentication-scheme|authorization-scheme|accounting-scheme"
    r"|domain default|local-user admin)\b",
    re.I,
)
# 出现这些就说明这段是"题目要配的东西"，必须删掉
DROP_PAT = re.compile(
    r"^\s*(vlan|interface|ospf|rip|bgp|isis|stp|mstp|ip route|route-policy"
    r"|acl|prefix-list|port link-type|port trunk|port default|port hybrid"
    r"|ip address|dhcp|vrrp|eth-trunk|link-aggregation|ntp|snmp|telnet"
    r"|user-interface|ssh|mpls|vpn-instance|pim|igmp|qos|traffic)\b",
    re.I,
)


def split_blocks(text: str) -> list[str]:
    """华为配置按 `#` 分段。"""
    return [b.strip() for b in text.split("#")]


def clean_cfg(text: str) -> str:
    """把一份完整配置削成"只有名字的空设备"。"""
    sysname = ""
    m = re.search(r"^\s*sysname\s+(\S+)", text, re.M | re.I)
    if m:
        sysname = m.group(1).strip()

    keep: list[str] = []
    for blk in split_blocks(text):
        if not blk:
            continue
        first = blk.splitlines()[0] if blk.splitlines() else ""
        if DROP_PAT.match(first):
            continue
        if KEEP_PAT.match(first) or first.startswith("local-user") \
                or first.startswith("domain "):
            keep.append(blk)

    # sysname 段本身就满足 KEEP_PAT，已经在 keep 里了，别再手动加一遍
    if not keep:
        keep = [f"sysname {sysname}"] if sysname else []
    body = "\n#\n".join(keep)
    return f"#\n{body}\n#\nreturn\n" if body else "#\nreturn\n"


def rewrite_flash(path: Path, cleaner) -> tuple[bool, str]:
    """改写单个 flash.efz：保留私有头，替换内部的 vrpcfg.cfg。"""
    raw = path.read_bytes()
    zpos = raw.find(b"PK\x03\x04")
    if zpos <= 0:
        return False, "找不到 ZIP 数据（不是 flash.efz？）"
    head = raw[:zpos]
    try:
        zin = zipfile.ZipFile(io.BytesIO(raw[zpos:]))
    except zipfile.BadZipFile as e:
        return False, f"ZIP 损坏：{e}"

    names = [n for n in zin.namelist() if n.lower().endswith(".cfg")]
    if not names:
        return False, "ZIP 里没有 .cfg"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in zin.namelist():
            data = zin.read(n)
            if n.lower().endswith(".cfg"):
                try:
                    txt = data.decode("utf-8")
                except UnicodeDecodeError:
                    txt = data.decode("gbk", errors="replace")
                new = cleaner(txt)
                if new == txt:
                    return False, "内容无需变更（可能已清洗过）"
                data = new.encode("utf-8")
            zout.writestr(n, data)

    path.write_bytes(head + buf.getvalue())
    return True, "已清洗"


def lab_dirs() -> list[tuple[str, Path, str]]:
    """返回 [(编号, 实验目录, 实验名)]，编号以 knowledge/experiments 为准。"""
    num2name: dict[str, str] = {}
    for fp in sorted(DOC_DIR.glob("*.md")):
        m = re.match(r"^(\d+)-(.+)\.md$", fp.name)
        if m:
            num2name[m.group(1)] = m.group(2)
    out: list[tuple[str, Path, str]] = []
    for d in sorted(SRC_DIR.iterdir()):
        if not d.is_dir():
            continue
        num = next((n for n, nm in num2name.items()
                    if nm.replace("实验 ", "").strip() == d.name
                    or nm.strip() == d.name or d.name in nm), "")
        out.append((num, d, d.name))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="清空实验包设备的预置配置")
    ap.add_argument("--only", default="", help="只处理指定编号，逗号分隔")
    ap.add_argument("--restore", action="store_true", help="用 .orig 备份还原")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv[1:])

    want = {x.strip().zfill(2) for x in args.only.split(",") if x.strip()}
    items = lab_dirs()
    changed = skipped = failed = 0

    for num, d, name in items:
        if want and num not in want:
            continue
        flashes = sorted(d.glob("paper/*/flash.efz"))
        if not flashes:
            continue
        print(f"\n[{num or '--'}] {name}  ({len(flashes)} 台设备)")
        for fp in flashes:
            backup = fp.with_suffix(fp.suffix + ".orig")
            if args.restore:
                if backup.exists():
                    if not args.dry_run:
                        shutil.copy2(backup, fp)
                    print(f"  还原 {fp.parent.name}")
                    changed += 1
                else:
                    print(f"  无备份，跳过 {fp.parent.name}")
                    skipped += 1
                continue

            if not backup.exists():
                if args.dry_run:
                    print(f"  [将备份+清洗] {fp.parent.name}")
                    changed += 1
                    continue
                shutil.copy2(fp, backup)
            ok, msg = rewrite_flash(fp, clean_cfg)
            print(f"  {fp.parent.name}: {msg}")
            if ok:
                changed += 1
            else:
                failed += 1

    print(f"\n完成：处理 {changed} ｜ 失败 {failed} ｜ 跳过 {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
