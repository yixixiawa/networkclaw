"""TelnetSession 端到端测试：线程版「假设备」TCP 服务器，无需真机。

手法与 tools 里既有验证一致：华为风格 `<Fake-SW>` 提示符，覆盖
「唤醒回车 -> 提示符识别 -> 命令收发 -> 回显清洗（去命令回显行/去提示符行）」。
"""
import socket
import threading
import time

import pytest

from core.device_conn import TelnetSession


class FakeDevice:
    """极简华为风格设备：收到第一行后发提示符；之后每条命令回一行 OK + 提示符。"""

    def __init__(self) -> None:
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self.port = self._srv.getsockname()[1]
        self._srv.listen(1)
        self._stop = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        try:
            conn, _ = self._srv.accept()
        except OSError:
            return
        conn.settimeout(0.2)
        buf = b""
        deadline = time.time() + 10
        while buf.count(b"\n") < 1 and time.time() < deadline:   # 等唤醒回车
            try:
                buf += conn.recv(1024)
            except socket.timeout:
                continue
            except OSError:
                return
        conn.sendall(b"\r\n<Fake-SW>")
        while not self._stop.is_set():
            try:
                data = conn.recv(1024)
            except socket.timeout:
                continue
            except OSError:
                return
            if not data:
                return
            # 注意：回显内容不能以命令文本结尾，否则会撞上客户端的
            # 「首行命令回显清洗」规则（first.endswith(command) 也算回显）
            conn.sendall(b"\r\nVRP-software-reply\r\n<Fake-SW>")
        conn.close()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._srv.close()
        except OSError:
            pass


@pytest.fixture()
def fake_device():
    dev = FakeDevice()
    time.sleep(0.1)
    yield dev
    dev.stop()


def test_telnet_roundtrip(fake_device):
    s = TelnetSession("127.0.0.1", fake_device.port, connect_timeout=5, timeout=8)
    try:
        seen = s.login()                       # 唤醒 + 提示符识别
        assert "<Fake-SW>" in seen
        out = s.exec_command("display version")
        assert "VRP-software-reply" in out     # 回显清洗后应保留设备响应
        assert not out.rstrip().endswith(">")  # 不应带出提示符行
    finally:
        s.close()


def test_telnet_iac_negation_is_filtered(fake_device):
    """假设备若发 Telnet 选项协商（IAC），客户端必须拒掉而不是把控制字节混进回显。"""
    s = TelnetSession("127.0.0.1", fake_device.port, connect_timeout=5, timeout=8)
    try:
        s.login()
        assert "\xff" not in s.exec_command("display clock")
    finally:
        s.close()
