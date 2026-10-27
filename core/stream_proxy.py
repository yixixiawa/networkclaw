"""标准流代理：把 print 输出同时写进原流与界面日志。

为什么单独成模块（2026-10-27）：
    这个类原本住在 ``gui/main_window.py`` 里，而那个模块顶层就 ``from PyQt6...``。
    于是任何想测 StreamProxy 的代码（``tests/test_gui_stream_proxy.py``）都被迫
    依赖 PyQt6；CI（.github/workflows/ci.yml）为了控制安装体积**故意不装 PyQt6**，
    结果 pytest 在 collection 阶段就 ``ModuleNotFoundError: No module named 'PyQt6'``
    中断（退出码 2）。StreamProxy 本身只用到 io，与 Qt 没有一点关系，移到 core 后
    GUI 仍是唯一使用方，测试却能脱离 GUI 依赖运行。

行为约定（两条都踩过坑，见 tests/test_gui_stream_proxy.py）：
    1. ``encoding`` / ``errors`` 必须是**类属性**。``io.TextIOBase`` 的同名成员是
       只读 getset 描述符，在 ``__init__`` 里赋值会抛
       ``AttributeError: attribute 'encoding' of '_io._TextIOBase' objects is not writable``，
       表现为 GUI 一启动就崩。
    2. ``fileno()`` 必须转发给原流。``TextIOBase`` 的默认实现抛
       ``io.UnsupportedOperation("fileno")``，而 fastmcp 的 StdioTransport 会把
       ``sys.stderr`` 作为子进程 errlog 交给 anyio，anyio 会调 ``.fileno()``——
       转发缺失时 7 个 MCP 服务端全部报 ``Client failed to connect: fileno``。
"""
import io


class StreamProxy(io.TextIOBase):
    """把 print 输出同时写进原流与界面日志（便于观察检索/工具调用细节）。

    为什么不用 sys.stdout = StringIO：MCP 子进程与部分库会访问 ``.buffer`` /
    ``fileno()``，这里保留对原始流与其 buffer 的转发，避免破坏它们。
    """

    # 注意：io.TextIOBase 的 encoding / errors 是只读 getset 描述符（Python 3.13+
    # 尤其严格），在 __init__ 里 self.encoding = ... 会抛
    # AttributeError: attribute 'encoding' of '_io._TextIOBase' objects is not writable。
    # 因此只能声明为类属性（类字典优先于基类描述符，实例读取即返回这里）。
    encoding = "utf-8"
    errors = "replace"

    def __init__(self, original, emit):
        self._orig = original
        self._emit = emit
        self._buf = getattr(original, "buffer", None)

    @property
    def buffer(self):
        return self._buf if self._buf is not None else self

    def fileno(self):
        """转发到底层流。

        为什么必须有：fastmcp 的 StdioTransport 默认把 sys.stderr 作为子进程的
        errlog 传给 anyio.open_process，anyio 会对它调 .fileno()。
        TextIOBase 的默认实现抛 io.UnsupportedOperation("fileno")，会被 fastmcp
        包成 "Client failed to connect: fileno"，表现为所有 MCP 服务端连接失败。
        """
        orig = self._orig
        if orig is None:
            raise io.UnsupportedOperation("fileno")
        fn = getattr(orig, "fileno", None)
        if fn is None:
            raise io.UnsupportedOperation("fileno")
        return fn()

    def write(self, text):  # type: ignore[override]
        if not text:
            return 0
        try:
            if self._orig is not None:
                self._orig.write(text)
                self._orig.flush()
        except Exception:
            pass
        try:
            self._emit(text)
        except Exception:
            pass
        return len(text)

    def writable(self) -> bool:
        return True

    def flush(self):  # type: ignore[override]
        try:
            if self._orig is not None:
                self._orig.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False
