"""检测 models/ 目录下有哪些可用的本地模型（.gguf）。

范围约定（2026-10-27，按用户要求）：
    **只检索 models/ 目录**（含一层子目录，排除 Ollama 风格的 blobs/manifests 等非
    gguf 数据目录），不做全盘搜索、不做 PATH 工具扫描。

「可用」的判定（全部只读文件头，不加载权重）：
    1. 文件存在且大小 > 1MB —— 排除损坏占位/下载残留
    2. 文件头 magic == b"GGUF" 且 version ∈ {1, 2, 3}
    3. 能完整解析出 general.architecture 元数据 —— 说明头部未截断，
       llama.cpp 能读出张量清单（张量数据损坏不在此检测范围）

角色区分：
    文件名含 mmproj → 视觉投影（multimodal projector），只能配合主模型使用，
    不能单独跑对话；其余视为主模型候选。

用法：
    python tools/check_models.py            # 表格输出
    python tools/check_models.py --json     # 机读输出（同时落盘 logs/models_check.json）
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE / "models"
OUT_JSON = BASE / "logs" / "models_check.json"

MIN_SIZE = 1 << 20  # 1MB
GGUF_MAGIC = b"GGUF"
KNOWN_VERSIONS = {1, 2, 3}

# 元数据里值得展示的键
INTERESTING_KEYS = (
    "general.architecture",
    "general.name",
    "general.file_type",
    "general.size_label",
    "general.quantization_imatrix",
    "general.license",
    "{arch}.block_count",
    "{arch}.context_length",
    "{arch}.embedding_length",
    "{arch}.attention.head_count",
    "{arch}.vision.block_count",
)

# GGUF 元数据值类型 → struct 格式（标量）
_SCALAR_FMT = {
    0: "<B", 1: "<b", 2: "<H", 3: "<h",
    4: "<I", 5: "<i", 6: "<f",
    7: "<B",  # bool
    10: "<Q", 11: "<q", 12: "<d",
}
_SCALAR_SIZE = {k: struct.calcsize(v) for k, v in _SCALAR_FMT.items()}
T_STRING = 8
T_ARRAY = 9


def _read_scalar(f, vtype: int):
    fmt = _SCALAR_FMT[vtype]
    raw = f.read(_SCALAR_SIZE[vtype])
    if len(raw) != _SCALAR_SIZE[vtype]:
        raise EOFError("标量读取截断")
    val = struct.unpack(fmt, raw)[0]
    return bool(val) if vtype == 7 else val


def _read_value(f, vtype: int):
    """读取一个元数据值。数组只保留前几个元素展示，但必须精确跳过整个数组。"""
    if vtype == T_STRING:
        n = _read_scalar(f, 10)
        return f.read(n).decode("utf-8", "replace")
    if vtype == T_ARRAY:
        etype = struct.unpack("<I", f.read(4))[0]
        count = _read_scalar(f, 10)
        if count > 5_000_000:
            raise ValueError(f"数组元素数异常: {count}")
        if etype == T_STRING:
            vals = []
            for i in range(count):
                ln = _read_scalar(f, 10)
                if i < 4:
                    vals.append(f.read(ln).decode("utf-8", "replace"))
                else:
                    f.seek(ln, 1)
            return vals[:4] + ([f"...共{count}项"] if count > 4 else [])
        if etype in _SCALAR_SIZE:
            step = _SCALAR_SIZE[etype]
            keep = min(count, 4)
            vals = [struct.unpack(_SCALAR_FMT[etype], f.read(step))[0] for _ in range(keep)]
            f.seek((count - keep) * step, 1)
            return vals + ([f"...共{count}项"] if count > 4 else [])
        # 嵌套数组（罕见）：逐个递归
        vals = [_read_value(f, etype) for _ in range(min(count, 4))]
        for _ in range(max(0, count - 4)):
            _read_value(f, etype)
        return vals
    if vtype in _SCALAR_FMT:
        return _read_scalar(f, vtype)
    raise ValueError(f"未知元数据类型: {vtype}")


def parse_gguf_header(path: Path) -> dict:
    """解析 GGUF 头与元数据。任何一步失败都返回带 error 的结果，绝不抛异常。"""
    out: dict = {"version": None, "tensor_count": None, "metadata": {}}
    try:
        with path.open("rb") as f:
            magic = f.read(4)
            if magic != GGUF_MAGIC:
                out["error"] = f"文件头不是 GGUF（前 4 字节: {magic!r}）"
                return out
            version = struct.unpack("<I", f.read(4))[0]
            out["version"] = version
            if version not in KNOWN_VERSIONS:
                out["error"] = f"GGUF 版本不受支持: v{version}"
                return out
            out["tensor_count"] = struct.unpack("<Q", f.read(8))[0]
            kv_count = struct.unpack("<Q", f.read(8))[0]
            if kv_count > 10_000:
                out["error"] = f"元数据条目数异常: {kv_count}"
                return out
            md = out["metadata"]
            arch_guess = ""
            for _ in range(kv_count):
                klen = _read_scalar(f, 10)
                key = f.read(klen).decode("utf-8", "replace")
                vtype = struct.unpack("<I", f.read(4))[0]
                val = _read_value(f, vtype)
                if key == "general.architecture":
                    arch_guess = str(val)
                md[key] = val
            out["ok"] = True
            return out
    except Exception as exc:  # noqa: BLE001 —— 损坏文件是预期输入，不是程序错误
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["metadata"] = out.get("metadata") or {}
        return out


def _rel(path: Path) -> str:
    """相对项目根的展示路径；models/ 之外的路径（如测试临时目录）回退为绝对路径。"""
    try:
        return str(path.relative_to(BASE))
    except ValueError:
        return str(path)


def check_file(path: Path) -> dict:
    """单个 .gguf 的可用性检测。"""
    size = path.stat().st_size
    r = parse_gguf_header(path)
    md = r.get("metadata") or {}
    is_mmproj = "mmproj" in path.name.lower()
    reasons: list[str] = []
    if size < MIN_SIZE:
        reasons.append(f"文件过小（{size} 字节 < 1MB，疑似损坏/占位）")
    if r.get("error"):
        reasons.append(r["error"])
    arch = md.get("general.architecture")
    if not reasons and not arch:
        reasons.append("缺少 general.architecture 元数据（头部不完整）")
    return {
        "file": _rel(path),
        "size_bytes": size,
        "size_human": f"{size / (1 << 30):.2f} GB",
        "role": "mmproj(视觉投影)" if is_mmproj else "主模型",
        "usable": not reasons,
        "problems": reasons,
        "gguf_version": r.get("version"),
        "tensor_count": r.get("tensor_count"),
        "architecture": arch,
        "name": md.get("general.name"),
        "size_label": md.get("general.size_label"),
        "context_length": next(
            (v for k, v in md.items() if k.endswith(".context_length")), None),
        "block_count": next(
            (v for k, v in md.items() if k.endswith(".block_count")), None),
    }


def main() -> int:
    json_mode = "--json" in sys.argv
    files: list[Path] = []
    if MODELS_DIR.is_dir():
        # 只看 models/ 顶层与一层子目录；blobs/manifests/.cache 等 Ollama 数据目录跳过
        files = sorted(MODELS_DIR.glob("*.gguf"))
        skip_top = {"blobs", "manifests", "metadata", ".cache"}
        for sub in MODELS_DIR.iterdir():
            if sub.is_dir() and sub.name not in skip_top:
                files += sorted(sub.glob("*.gguf"))
    # 去重（一层子目录若与顶层同名不太可能，防御一下）
    seen: set[str] = set()
    files = [p for p in files if not (str(p) in seen or seen.add(str(p)))]  # type: ignore[func-returns-value]

    results = [check_file(p) for p in files]
    usable_main = [r for r in results if r["usable"] and r["role"] == "主模型"]
    usable_mmproj = [r for r in results if r["usable"] and "mmproj" in r["role"]]
    payload = {
        "models_dir": str(MODELS_DIR),
        "dir_exists": MODELS_DIR.is_dir(),
        "scanned": len(results),
        "usable_main_models": len(usable_main),
        "usable_mmproj": len(usable_mmproj),
        "results": results,
    }

    if json_mode:
        OUT_JSON.parent.mkdir(exist_ok=True)
        OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0

    print(f"检测目录: {MODELS_DIR}（存在={MODELS_DIR.is_dir()}）")
    if not results:
        print("结论: models/ 下没有任何 .gguf 文件 —— 没有可用模型")
        return 1
    for r in results:
        flag = "✓ 可用" if r["usable"] else "✗ 不可用"
        print(f"\n[{flag}] {r['file']}")
        print(f"    角色: {r['role']}    大小: {r['size_human']}")
        if r["usable"]:
            print(f"    GGUF v{r['gguf_version']}  架构: {r['architecture']}"
                  f"  名称: {r['name'] or '-'}  规格: {r['size_label'] or '-'}")
            print(f"    层数: {r['block_count']}  上下文: {r['context_length']}"
                  f"  张量数: {r['tensor_count']}")
        else:
            for p in r["problems"]:
                print(f"    原因: {p}")
    print(f"\n结论: 可用主模型 {len(usable_main)} 个 / 可用视觉投影 {len(usable_mmproj)} 个"
          f"（共扫描 {len(results)} 个 .gguf）")
    if usable_main:
        print(f"启动提示: 主模型自动选用 {usable_main[0]['file']}"
              f"（可用环境变量 NETWORKCLAW_MODEL 指定其他文件）"
              + (f"；识图需 --mmproj {usable_mmproj[0]['file']}" if usable_mmproj else
                 "；未发现 mmproj，识图不可用"))
    return 0 if (usable_main or usable_mmproj) else 1


if __name__ == "__main__":
    sys.exit(main())
