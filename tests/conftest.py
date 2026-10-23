"""pytest 全局配置：把项目根加进 sys.path（tests 在子目录也能 import core/tools）。

另有一个 autouse 夹具：把「会话技能根目录」与「运行日志根目录」隔离到临时目录。
为什么必须隔离：`core/device_manual.py` 的所有路径都经 `core/session_skills`
解析，任何碰到手册/历史的测试如果不隔离，就会读写真实的 `session/` 目录、
甚至覆盖真实的 `session/.current` 指针——那会把开发者机器上「当前对话」
改成测试用的 sid。
"""
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core import session_skills as ss  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_session_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "SESSIONS_DIR", tmp_path / "session")
    try:
        from core import run_log

        monkeypatch.setattr(run_log, "LOG_ROOT", tmp_path / "run_logs")
    except Exception:
        pass
    yield
    # 收尾：清掉进程内钉住的会话与指针缓存，避免污染同进程内的后续测试
    ss._pinned = None
    ss._cache.update({"sid": ss.DEFAULT_SID, "stamp": None})
