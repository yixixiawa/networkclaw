"""虚拟机 ↔ 宿主 HTTP 文件桥（绕过 vmrun copyFileFromGuestToHost 的不可靠）。

背景：本机 vmrun 的 `copyFileFromGuestToHost` 会间歇性报
`Error: 文件名无效`，无法作为稳定传输通道；宿主机（192.168.10.1）与虚拟机
（192.168.10.128）同网段，直接走 HTTP 更稳。

用法：
    python tools/vm_bridge.py serve [--port 8899] [--root data/vm_bridge]
    python tools/vm_bridge.py fetch <来宾路径> [--out 本地文件名]   # 从访客拉文件

访客侧（PowerShell，走 tools/vm_guest.py）：
    上传：Invoke-WebRequest -Uri http://192.168.10.1:8899/inbox/x.zip -Method Put -InFile C:\\x.zip -UseBasicParsing
    下载：Invoke-WebRequest -Uri http://192.168.10.1:8899/outbox/y.txt -OutFile C:\\y.txt -UseBasicParsing

路由：
    GET  /ping                  -> pong
    GET  /<相对路径>             -> 从 root 读取文件返回
    PUT  /<相对路径>             -> 把请求体写入 root/<相对路径>
    GET  /__list                -> 列出 root 下所有文件
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = BASE_DIR / "data" / "vm_bridge"
HOST_IP = os.environ.get("VM_BRIDGE_HOST", "192.168.1.249")
PORT = int(os.environ.get("VM_BRIDGE_PORT", "8899"))

ROOT: Path = DEFAULT_ROOT
_counter = {"puts": 0, "gets": 0}


def _safe(root: Path, rel: str) -> Path | None:
    """把 URL 路径映射到 root 下，拒绝越权。"""
    rel = unquote(rel).lstrip("/\\")
    if not rel:
        return None
    p = (root / rel).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError:
        return None
    return p


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "VmBridge/1.0"

    def log_message(self, fmt, *args):  # 静默
        pass

    # ------------------------------------------------------------ helpers
    def _send(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    # ------------------------------------------------------------ verbs
    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/ping":
            self._send(200, b"pong")
            return
        if path == "/__list":
            files = []
            if ROOT.exists():
                for p in sorted(ROOT.rglob("*")):
                    if p.is_file():
                        files.append(f"{p.relative_to(ROOT)} | {p.stat().st_size}")
            self._send(200, "\n".join(files).encode("utf-8"))
            return
        target = _safe(ROOT, path)
        if target is None or not target.is_file():
            self._send(404, f"not found: {path}".encode("utf-8"))
            return
        data = target.read_bytes()
        _counter["gets"] += 1
        ctype = "application/octet-stream"
        if target.suffix.lower() in (".txt", ".md", ".json", ".csv"):
            ctype = "text/plain; charset=utf-8"
        self._send(200, data, ctype)

    def do_PUT(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        target = _safe(ROOT, urlparse(self.path).path)
        if target is None:
            self._send(400, b"bad path")
            return
        body = self.rfile.read(length) if length else b""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        _counter["puts"] += 1
        print(f"[bridge] PUT {target.relative_to(ROOT)} <- {len(body)} bytes")
        self._send(200, f"stored {len(body)} bytes".encode("utf-8"))


def serve(root: Path, port: int):
    global ROOT
    ROOT = root
    ROOT.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST_IP, port), Handler)
    print(f"[bridge] listening on http://{HOST_IP}:{port}  root={ROOT}")
    sys.stdout.flush()
    httpd.serve_forever()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["serve", "list"])
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args(argv[1:])
    if args.cmd == "serve":
        serve(Path(args.root), args.port)
    else:
        r = Path(args.root)
        for p in sorted(r.rglob("*")):
            if p.is_file():
                print(f"{p.relative_to(r)} | {p.stat().st_size}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
