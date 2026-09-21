"""设备连接层：串口（Console）与 Telnet 两种通道的会话实现。

为什么自己写 Telnet：
    Python 3.13 起标准库 telnetlib 已被移除（本项目 venv 为 3.14），
    而 telnetlib3 会引入额外依赖。网络设备 CLI 只需要最朴素的一点点 Telnet 协商，
    因此这里用 socket 实现一个最小可用客户端：拒绝所有选项协商（设备 CLI 不需要），
    直接进入交互，行为可控且无第三方依赖。

两条通道共享的会话能力：
    - 提示符识别：<Huawei> / [SW1] / Router> / SW1# 等主流设备提示符
    - 分页自动翻页：遇到 "---- More ----" / "--More--" 自动补空格
    - 关分页：自动发送三家只读的关分页命令（经 command_guard 判定为 allow 才发）
    - 编码容错：先按 utf-8 解，失败退 gbk（国产设备回显常为 gbk）
    - 输出清洗：去掉 ANSI 转义、命令回显、末尾提示符

被 mcp_tools/device_server.py（串口）与 mcp_tools/telnet_server.py（Telnet）调用。
只负责「怎么连、怎么收发」；「什么命令能发」由 core.command_guard 决定。
"""
import re
import socket
import time

from core.command_guard import ALLOW, classify_one

# ---------------------------------------------------------------- 编码与清洗

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b[()][A-Z0-9]|\x08")


def decode_bytes(data: bytes) -> str:
    """设备回显编码容错：utf-8 → gbk → 忽略非法字节"""
    if not data:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def encode_text(text: str) -> bytes:
    """发送内容编码：优先 utf-8，中文设备名退回 gbk"""
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        return text.encode("gbk", errors="replace")


def clean_output(text: str) -> str:
    """去掉 ANSI 转义、回车、分页提示与多余空行"""
    text = _ANSI_RE.sub("", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[-—\s]*More[-—\s]*\n?", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<--- More --->", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_iac_bytes(data: bytes) -> bytes:
    """只丢弃 Telnet IAC 协商字节（不回包），用于一次性探测场景"""
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if b != 255:                                  # 255 = IAC
            out.append(b)
            i += 1
        elif i + 1 < n and data[i + 1] == 255:        # IAC IAC = 转义的 255
            out.append(255)
            i += 2
        elif i + 2 < n and data[i + 1] in (251, 252, 253, 254):  # WILL/WONT/DO/DONT + 选项
            i += 3
        else:
            i += 2
    return bytes(out)


# ---------------------------------------------------------------- 提示符识别

PROMPT_RE = re.compile(
    r"(?:"
    r"[<\[]\s*[A-Za-z0-9_\-\u4e00-\u9fa5\.]{1,64}\s*[>\]]\s*$"      # <Huawei>  [SW1]
    r"|^[A-Za-z0-9_\-\u4e00-\u9fa5\.]{1,64}[#>]\s*$"                 # SW1#   Router>
    r"|\(config[^)]*\)[#>]\s*$"                                      # (config)#
    r")",
    re.MULTILINE,
)

MORE_MARKERS = ("---- More ----", "--More--", "<--- More --->", "---- More ----")

USER_PROMPTS = ("username:", "user name:", "user:", "login as:", "login:",
                "please input user", "please enter user")
PASSWORD_PROMPTS = ("password:", "passwd:", "please input password", "enter password")

# 三家关分页命令（均在用户视图执行、只影响当前会话，非持久化配置）
PAGING_OFF_COMMANDS = ("screen-length 0 temporary", "screen-length disable", "terminal length 0")


def has_prompt(text: str) -> bool:
    """文本尾部是否出现设备命令行提示符"""
    if not text:
        return False
    tail = text[-200:]
    return bool(PROMPT_RE.search(tail))


def _tail_has(text: str, keys: tuple[str, ...], window: int = 160) -> bool:
    """最近一段文本里是否出现某类提示（避开 banner 里历史关键词的误判）"""
    low = (text or "")[-window:].lower()
    return any(k in low for k in keys)


class DeviceError(RuntimeError):
    """设备连接/通信异常（工具层会转成可读文本返回）"""


# ---------------------------------------------------------------- 会话基类

class BaseSession:
    """串口 / Telnet 会话的公共收发逻辑"""

    #: 'serial' / 'telnet'，用于审计
    transport = "unknown"

    def __init__(self, timeout: float = 20.0, read_slice: float = 0.4):
        self.timeout = timeout
        self.read_slice = read_slice
        self.raw_log: list[str] = []      # 原始字节计数等调试信息（不返回给模型）
        self._closed = False

    # ------- 子类实现
    def _read_chunk(self, timeout: float) -> bytes:
        raise NotImplementedError

    def _write(self, data: bytes) -> None:
        raise NotImplementedError

    def close(self) -> None:
        self._closed = True

    # ------- 通用能力
    def write_line(self, text: str, newline: str = "\r\n") -> None:
        self._write(encode_text(text + newline))
        self.raw_log.append(f">>> {text}")

    def read_until(self, predicate, timeout: float | None = None) -> str:
        """持续读取，直到 predicate(累积文本, 本轮新增文本) 为真或超时"""
        deadline = time.time() + (self.timeout if timeout is None else timeout)
        buf = ""
        while time.time() < deadline:
            try:
                chunk = self._read_chunk(self.read_slice)
            except socket.timeout:
                chunk = b""
            if chunk:
                buf += decode_bytes(chunk)
                if predicate(buf, buf[-400:]):
                    return buf
            else:
                # 没有新数据时也检查一次（例如对方已回完但无提示符）
                if predicate(buf, ""):
                    return buf
        return buf

    def read_until_prompt(self, timeout: float | None = None, auto_more: bool = True) -> str:
        """读到出现设备提示符为止；期间自动处理分页"""
        deadline = time.time() + (self.timeout if timeout is None else timeout)
        buf = ""
        last_data = time.time()
        more_count = 0

        while time.time() < deadline:
            try:
                chunk = self._read_chunk(self.read_slice)
            except socket.timeout:
                chunk = b""
            if chunk:
                text = decode_bytes(chunk)
                buf += text
                last_data = time.time()
                if auto_more and any(m in text for m in MORE_MARKERS) and more_count < 50:
                    self._write(b" ")          # 翻页
                    more_count += 1
                continue

            # 无新数据：若已出现提示符且安静了 0.4 秒，认为本次回显结束
            if has_prompt(buf) and (time.time() - last_data) >= 0.4:
                return buf
        return buf

    def prepare(self, disable_paging: bool = True) -> str:
        """会话建立后的初始化：关闭分页，避免长回显被 "---- More ----" 截断"""
        self.drain(quiet=0.25)   # 丢掉登录/banner 残留，保证后续「一问一答」不错位
        if not disable_paging:
            return ""
        info = []
        for cmd in PAGING_OFF_COMMANDS:
            # 自查：只有被网关判定为 allow 的会话内务命令才允许自动下发
            if classify_one(cmd)["level"] != ALLOW:
                continue
            self.write_line(cmd)
            text = clean_output(self.read_until_prompt(timeout=6))
            info.append(f"{cmd} -> {text.splitlines()[-1] if text else '(无回显)'}")
        # 关分页失败不影响使用，只是长输出需要自动翻页
        return "；".join(info)

    def drain(self, quiet: float = 0.3, limit: float = 2.0) -> str:
        """清空发送命令前缓冲里的残留数据，保证「一问一答」不错位"""
        deadline = time.time() + limit
        last = time.time()
        buf = ""
        while time.time() < deadline:
            try:
                chunk = self._read_chunk(0.15)
            except (socket.timeout, OSError):
                chunk = b""
            if chunk:
                buf += decode_bytes(chunk)
                last = time.time()
            elif time.time() - last >= quiet:
                break
        return buf

    def exec_command(self, command: str, timeout: float | None = None) -> str:
        """发送一条命令并返回清洗后的回显（不含命令回显行与末尾提示符）"""
        self.drain()
        start = time.time()
        self.write_line(command)
        raw = self.read_until_prompt(timeout=timeout)
        text = clean_output(raw)

        # 去掉命令自身回显（首行通常与命令一致，忽略大小写与空白差异）
        lines = text.splitlines()
        if lines:
            first = re.sub(r"\s+", " ", lines[0]).strip().lower()
            if first == re.sub(r"\s+", " ", command).strip().lower() or first.endswith(
                    re.sub(r"\s+", " ", command).strip().lower()):
                lines = lines[1:]
        # 去掉末尾提示符行
        if lines and PROMPT_RE.search(lines[-1]):
            lines = lines[:-1]
        body = "\n".join(lines).strip()
        self.raw_log.append(f"<<< {len(raw)} bytes in {time.time() - start:.1f}s")
        return body


# ---------------------------------------------------------------- 串口会话

class SerialSession(BaseSession):
    """串口（Console）会话。

    port 支持真实端口（COM3 / /dev/ttyUSB0）与 pyserial 的 URL 形式（loop:// 用于自测）。
    """

    transport = "serial"

    def __init__(self, port: str, baudrate: int = 9600, bytesize: int = 8,
                 parity: str = "N", stopbits: float = 1, timeout: float = 20.0,
                 read_slice: float = 0.3):
        super().__init__(timeout=timeout, read_slice=read_slice)
        try:
            import serial  # pyserial
        except ImportError as e:  # pragma: no cover
            raise DeviceError("未安装 pyserial，无法使用串口：pip install pyserial") from e

        try:
            self.ser = serial.serial_for_url(
                port, baudrate=baudrate, bytesize=bytesize, parity=parity,
                stopbits=stopbits, timeout=read_slice, write_timeout=5,
            )
        except Exception as e:
            raise DeviceError(
                f"打开串口 {port} 失败：{type(e).__name__}: {e}。"
                f"请确认端口号、是否被其他程序（如 SecureCRT / 串口助手）占用。"
            ) from e
        self.port = port

    def _read_chunk(self, timeout: float) -> bytes:
        # 有数据就一次取完，避免逐字节 read 拖慢速度
        waiting = getattr(self.ser, "in_waiting", 0)
        n = waiting if waiting else 1
        return self.ser.read(n)

    def _write(self, data: bytes) -> None:
        self.ser.write(data)
        self.ser.flush()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.ser.close()
        except Exception:
            pass
        self._closed = True


# ---------------------------------------------------------------- Telnet 会话

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240


class TelnetSession(BaseSession):
    """最小 Telnet 客户端：拒绝全部选项协商，只做「发命令 / 收回显」"""

    transport = "telnet"

    def __init__(self, host: str, port: int = 23, connect_timeout: float = 8.0,
                 timeout: float = 20.0, read_slice: float = 0.4):
        super().__init__(timeout=timeout, read_slice=read_slice)
        self.host = host
        self.port = port
        try:
            self.sock = socket.create_connection((host, port), timeout=connect_timeout)
        except OSError as e:
            raise DeviceError(
                f"连接 {host}:{port} 失败：{e}。请确认设备已开启 Telnet 服务、"
                f"网络可达（可先用 telnet_check 探测端口连通性）。"
            ) from e
        self.sock.settimeout(read_slice)

    # ---- IAC 选项协商：一律拒绝（设备 CLI 不需要任何 Telnet 选项）
    def _filter_iac(self, data: bytes) -> bytes:
        out = bytearray()
        i, n = 0, len(data)
        while i < n:
            b = data[i]
            if b != IAC:
                out.append(b)
                i += 1
                continue
            if i + 1 >= n:
                break
            cmd = data[i + 1]
            if cmd == IAC:                      # 转义的 255
                out.append(IAC)
                i += 2
            elif cmd in (DO, DONT, WILL, WONT):
                if i + 2 >= n:
                    break
                opt = data[i + 2]
                reply = WONT if cmd == DO else DONT
                try:
                    self.sock.sendall(bytes([IAC, reply, opt]))
                except OSError:
                    pass
                i += 3
            elif cmd == SB:                     # 子协商：整段丢弃
                j = data.find(bytes([IAC, SE]), i + 2)
                i = n if j == -1 else j + 2
            else:                               # 单字节命令（NOP/GA 等）
                i += 2
        return bytes(out)

    def _read_chunk(self, timeout: float) -> bytes:
        self.sock.settimeout(timeout)
        try:
            data = self.sock.recv(4096)
        except socket.timeout:
            return b""
        if not data:
            raise DeviceError(f"设备 {self.host}:{self.port} 主动断开了连接")
        return self._filter_iac(data)

    def _write(self, data: bytes) -> None:
        self.sock.sendall(data)

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.sock.close()
        except Exception:
            pass
        self._closed = True

    # ---- 登录
    def login(self, username: str = "", password: str = "", enable_password: str = "",
              timeout: float = 15.0) -> str:
        """按设备提示自动完成「用户名 → 密码 → (可选) enable」三步登录。

        返回登录过程中收集到的文本（仅用于诊断，不作为命令输出）。
        """
        seen = self.read_until(
            lambda buf, new: has_prompt(buf)
            or _tail_has(buf, USER_PROMPTS)
            or _tail_has(buf, PASSWORD_PROMPTS),
            timeout=timeout,
        )

        if username and _tail_has(seen, USER_PROMPTS) and not has_prompt(seen):
            self.write_line(username)
            seen = self.read_until(
                lambda buf, new: has_prompt(buf) or _tail_has(buf, PASSWORD_PROMPTS),
                timeout=timeout,
            )

        if password and _tail_has(seen, PASSWORD_PROMPTS) and not has_prompt(seen):
            self.write_line(password)
            seen = self.read_until(lambda buf, new: has_prompt(buf), timeout=timeout)

        # Cisco 风格：登录后是 "Router>"，需要 enable 才能进特权模式
        if enable_password and has_prompt(seen) and seen.rstrip().endswith(">"):
            self.write_line("enable")
            e = self.read_until(
                lambda buf, new: has_prompt(buf) or _tail_has(buf, PASSWORD_PROMPTS),
                timeout=timeout,
            )
            if _tail_has(e, PASSWORD_PROMPTS) and not has_prompt(e):
                self.write_line(enable_password)
                e = self.read_until(lambda buf, new: has_prompt(buf), timeout=timeout)
            seen += e

        if not has_prompt(seen):
            raise DeviceError(
                "登录后未识别到设备提示符（可能需要用户名/密码，或设备开启了其他认证方式）。"
                f"设备回显片段：{clean_output(seen)[-200:]!r}"
            )
        return seen


# ---------------------------------------------------------------- 对外便捷入口

def open_serial(port: str, baudrate: int = 9600, timeout: float = 20.0,
                disable_paging: bool = True) -> SerialSession:
    """打开串口会话（Console 口默认无需登录）"""
    sess = SerialSession(port=port, baudrate=baudrate, timeout=timeout)
    try:
        sess.prepare(disable_paging=disable_paging)
    except Exception:
        pass  # 关分页失败不影响后续执行
    return sess


def open_telnet(host: str, port: int = 23, username: str = "", password: str = "",
                enable_password: str = "", timeout: float = 20.0,
                disable_paging: bool = True) -> TelnetSession:
    """建立 Telnet 会话并登录"""
    sess = TelnetSession(host=host, port=port, timeout=timeout)
    try:
        sess.login(username=username, password=password,
                   enable_password=enable_password, timeout=min(15.0, timeout))
        sess.prepare(disable_paging=disable_paging)
    except Exception:
        sess.close()
        raise
    return sess


def list_serial_ports() -> list[dict]:
    """列出本机可用串口"""
    try:
        from serial.tools import list_ports
    except ImportError as e:
        raise DeviceError("未安装 pyserial，无法枚举串口：pip install pyserial") from e
    return [
        {
            "device": p.device,
            "description": p.description or "",
            "hwid": p.hwid or "",
        }
        for p in list_ports.comports()
    ]


def probe_tcp(host: str, port: int = 23, timeout: float = 5.0) -> dict:
    """TCP 端口连通性探测（只读，不下发任何命令）"""
    start = time.time()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as e:
        return {"ok": False, "host": host, "port": port,
                "elapsed": round(time.time() - start, 2), "error": str(e)}
    banner = b""
    try:
        sock.settimeout(1.5)
        try:
            banner = sock.recv(512)
        except socket.timeout:
            pass
    finally:
        sock.close()
    return {
        "ok": True, "host": host, "port": port,
        "elapsed": round(time.time() - start, 2),
        "banner": clean_output(decode_bytes(strip_iac_bytes(banner)))[:200],
    }
