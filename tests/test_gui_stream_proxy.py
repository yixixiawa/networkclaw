"""GUI 标准流代理（StreamProxy）的回归测试。

背景（2026-10-23 实测踩坑）：
1. ``StreamProxy`` 继承 ``io.TextIOBase``，而基类的 ``encoding`` / ``errors`` 是
   只读 getset 描述符，在 ``__init__`` 里赋值会抛
   ``AttributeError: attribute 'encoding' of '_io._TextIOBase' objects is not writable``，
   表现为 **GUI 一启动就崩，连窗口都看不到**。只能声明成类属性。
2. ``TextIOBase.fileno()`` 默认抛 ``io.UnsupportedOperation('fileno')``。fastmcp 的
   StdioTransport 默认把 ``sys.stderr`` 作为子进程 errlog 交给 anyio，anyio 会调
   ``fileno()``，于是 7 个 MCP 服务端**全部连接失败**，报
   ``RuntimeError: Client failed to connect: fileno``。必须把 fileno 转发给原流。

这两个坑都不会被普通 import 测试发现，所以在这里钉死。
"""
import io
import sys

from gui.main_window import StreamProxy


class _FakeStream(io.TextIOBase):
    """带真实 fileno 的可写流替身（模拟被重定向的 sys.stdout）"""

    def __init__(self):
        self.chunks: list[str] = []

    def writable(self) -> bool:
        return True

    def write(self, text):
        self.chunks.append(text)
        return len(text)

    def flush(self):
        pass

    def fileno(self):
        return 1  # 假装是 stdout 句柄，测试只关心「能转发出去」


def test_stream_proxy_has_writable_encoding_attributes():
    """encoding / errors 必须是可读的（类属性），构造过程不得抛 AttributeError"""
    s = StreamProxy(_FakeStream(), lambda text: None)
    assert s.encoding == "utf-8"
    assert s.errors == "replace"


def test_stream_proxy_write_forwards_to_original_and_emit():
    orig = _FakeStream()
    seen: list[str] = []
    s = StreamProxy(orig, seen.append)
    assert s.write("hello") == 5
    assert orig.chunks == ["hello"]
    assert seen == ["hello"]


def test_stream_proxy_forwards_fileno():
    """fastmcp/anyio 需要 errlog.fileno()，默认实现会抛 UnsupportedOperation"""
    s = StreamProxy(_FakeStream(), lambda text: None)
    assert s.fileno() == 1


def test_stream_proxy_without_fileno_raises_unsupported():
    """原流没有 fileno（如 StringIO）时，仍按标准语义抛 UnsupportedOperation"""
    s = StreamProxy(io.StringIO(), lambda text: None)
    try:
        s.fileno()
    except io.UnsupportedOperation:
        return
    raise AssertionError("缺少 fileno 时应抛 io.UnsupportedOperation")


def test_stream_proxy_buffer_falls_back_to_self():
    """原流没有 .buffer（非缓冲流）时返回自身，避免 AttributeError"""
    s = StreamProxy(io.StringIO(), lambda text: None)
    assert s.buffer is s


def test_stream_proxy_isatty_false_keeps_rich_output_plain():
    """GUI 里不应被当成终端（否则 rich/tqdm 会输出控制字符）"""
    s = StreamProxy(sys.stdout, lambda text: None)
    assert s.isatty() is False
