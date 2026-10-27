"""Embedding 与向量库接口层。

职责（只做这两件事）：
- 初始化 Ollama Embedding 模型（nomic-embed-text）
- 管理 ChromaDB 持久化客户端，并按「集合名」提供集合句柄

集合隔离约定：
- 集合名统一在本模块注册（KNOWLEDGE_COLLECTION / TEMPLATE_COLLECTION），
  其他模块不得再自行硬编码字符串，避免串库。
- 本模块**不导出**任何长生命周期的集合对象；业务模块一律通过
  get_collection(名字) 现取现用。这样某个模块重建集合（delete + create）时，
  不会让另一个模块手里的旧句柄失效（此前 rag.py 直接引用模块级 collection，
  一旦集合被重建就会指向已删除的对象）。
- 索引状态（指纹）按集合名分文件记录，两个集合互不影响。

物理上两套数据仍共用 data/Rag_data 目录（一个 Chroma 库、两个集合）。
"""
import hashlib
import json
import time

import chromadb
from chromadb.utils.embedding_functions.ollama_embedding_function import OllamaEmbeddingFunction

from core.net import ensure_localhost_bypass  # noqa: F401  (让 127.0.0.1:11434 绕过系统代理)
from core.paths import BASE_DIR  # 统一路径层：打包后指向 exe 所在目录

ensure_localhost_bypass()

CHROMA_PATH = BASE_DIR / "data" / "Rag_data"
INDEX_STATE_FILE = BASE_DIR / "data" / "index_state.json"
OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "nomic-embed-text"

# ---------------------------------------------------------------- 集合名注册表
KNOWLEDGE_COLLECTION = "huawei_devices"     # 知识库：设备介绍、配置说明
TEMPLATE_COLLECTION = "command_templates"   # 命令模板：knowledge/command_templates.csv

class BatchedOllamaEmbeddingFunction(OllamaEmbeddingFunction):
    """按小批量切分调用的 Ollama Embedding 函数。

    为什么需要：Chroma 会把**整批**文档一次性交给 embedding function。实测
    （1675 个知识块）一次提交 512 条就会把 Ollama 的 runner 打崩，接口返回
    ``400 Post "http://127.0.0.1:51686/tokenize": dial tcp ... refused``；
    128 条以内稳定。因此在 __call__ 内部切片，对外仍是同一个 Embedding 函数。

    注意：name() / get_config() 全部继承自父类，持久化配置与
    OllamaEmbeddingFunction 完全一致，不会造成已有集合的 embedding function 冲突。
    """

    batch_size = 64

    def __call__(self, input):
        seq = list(input)
        if len(seq) <= self.batch_size:
            return super().__call__(seq)
        out = []
        for i in range(0, len(seq), self.batch_size):
            out.extend(super().__call__(seq[i:i + self.batch_size]))
        return out


_embedding_fn = None


def get_embedding_function():
    """惰性构造 Ollama embedding 函数（进程内单例）。

    为什么不在模块级实例化（2026-10-27）：
        chromadb 的 OllamaEmbeddingFunction 在 ``__init__`` 里就 ``from ollama import
        Client``，缺 ollama 包会抛 ``ValueError: The ollama python package is not
        installed``。模块级实例化意味着**任何** import 本模块的代码——包括
        ``core.rag``、``core.template_search``，以及只想跑离线单测的 CI——都会被这个
        纯运行时依赖拖死（CI 的依赖清单里没有 ollama，pytest 直接 collection error）。
        ollama 是「检索时才需要」的外部服务客户端，首次真正检索时再构造即可。
    """
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = BatchedOllamaEmbeddingFunction(
            url=OLLAMA_URL,
            model_name=EMBED_MODEL,
        )
    return _embedding_fn


_client = None


def get_client():
    """进程内单例的 Chroma 持久化客户端"""
    global _client
    if _client is None:
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return _client


def get_collection(name: str):
    """按名获取集合句柄（不存在则创建）。每次调用返回新句柄，不缓存。"""
    return get_client().get_or_create_collection(
        name=name,
        embedding_function=get_embedding_function(),
    )


def reset_collection(name: str):
    """删除并重建集合（全量重建索引用），返回重建后的空集合句柄。

    注意：本函数会立刻丢弃旧数据，调用前必须先通过 check_embedder() 预检，
    否则 Embedding 服务不可用时会把旧索引清空且写不进新数据。
    """
    client = get_client()
    try:
        client.delete_collection(name)
    except Exception:
        pass  # 集合本就不存在，忽略
    return get_collection(name)


def check_embedder():
    """预检 Ollama Embedding 服务是否可用。

    重建索引是「先删后建」，若 Embedding 不可用会导致旧索引被清空，
    因此在任何重建动作之前调用本函数，失败时抛出带处理建议的异常。
    """
    try:
        get_embedding_function()(["ping"])
    except Exception as e:
        raise RuntimeError(
            "Ollama Embedding 服务不可用（http://127.0.0.1:11434）。\n"
            f"  原因：{type(e).__name__}: {e}\n"
            "  处理：先启动 Ollama（ollama serve 或桌面端），"
            "并确认模型已就位：ollama pull nomic-embed-text"
        ) from e


def collection_count(name: str) -> int:
    """集合内条目数（集合不存在时为 0）"""
    try:
        return get_collection(name).count()
    except Exception:
        return 0


# ------------------------------------------------------------ 索引指纹（各自独立）
def compute_fingerprint(source: str | list[str]) -> str:
    """计算数据源指纹：源文件文本或切分后的条目列表皆可"""
    h = hashlib.md5()
    if isinstance(source, str):
        h.update(source.encode("utf-8"))
    else:
        for item in source:
            h.update(item.encode("utf-8"))
            h.update(b"\x00")  # 分隔符，避免不同组合哈希相同
    return h.hexdigest()


def load_index_state(name: str) -> dict:
    """读取某个集合的索引状态（不存在返回空字典）"""
    if not INDEX_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(INDEX_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data.get(name, {})


def save_index_state(name: str, fingerprint: str, count: int, source: str = ""):
    """记录某个集合最近一次建索引的指纹（按集合名分区，互不覆盖）"""
    INDEX_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if INDEX_STATE_FILE.exists():
        try:
            data = json.loads(INDEX_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    data[name] = {
        "fingerprint": fingerprint,
        "count": count,
        "source": source,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    INDEX_STATE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def index_is_fresh(name: str, fingerprint: str, expected_count: int) -> bool:
    """索引是否与数据源一致：指纹相同且条数相同才算新鲜"""
    state = load_index_state(name)
    return (
        state.get("fingerprint") == fingerprint
        and state.get("count") == expected_count
    )
