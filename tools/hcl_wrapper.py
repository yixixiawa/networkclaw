"""HCL SimwareWrapper 控制协议客户端（宿主端运行，经 vmrun 在来宾执行）。

协议（2026-10-01 从 HCL 日志还原 + 实测验证）
--------------------------------------------
SimwareWrapper 是 Python HTTP 服务（默认 `--port 11525`，实测 HCL 启动时用 16600），
客户端（HCL GUI）**不自带 HTTP 头**地发「空格分隔的 token 行」，格式：

    <序号> <服务名> <命令> [参数...]

例：
    8 simware create_topology topo1 <工作目录> <会话名> 10000
    3 simwarewrapper version

**应答格式（实测）**：
    <序号>-<errorCode>-<返回值>
    /end
其中 errorCode=101 表示成功。实测：
    1 simwarewrapper version       -> 1-101-1.0.0&5.1.24
    2 simwarewrapper system_memory -> 2-101-7291

服务名：`simwarewrapper` / `simware` / `simwaremulticc`
命令（已确认存在）：
    simwarewrapper.version / system_memory
    simware.set_version_path <dir>
    simware.create_topology <topo> <workingdir> <session> <udp_port>
    simware.set_hcl_tcp <port>
    simware.set_hcl_normal_close True
    simware.normal_close True
    simwaremulticc.add_topology <dir> <session>
    simwaremulticc.handleRet_createTopo <ret> <dir> <session>
    simwaremulticc.simware_server_info <user>
    simwaremulticc.simware_hclserver_info
    simwaremulticc.normal_close True

用法（在来宾里跑）：
    python tools/hcl_wrapper.py probe <port>
    python tools/hcl_wrapper.py send <port> "<原样一行报文>"
    python tools/hcl_wrapper.py version <port>
    python tools/hcl_wrapper.py create <port> <工作目录> [topo名] [udp端口]
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))


def build_client_ps(port: int, payload: str, timeout: float = 6.0) -> str:
    """生成一段 PowerShell：TCP 连到 127.0.0.1:<port>，发一行，读回所有数据。"""
    safe = payload.replace("'", "''")
    return rf"""
Add-Type -Namespace HC -Name Net -MemberDefinition @'
public static string Talk(int port, string payload, int timeoutMs) {{
  try {{
    var c = new System.Net.Sockets.TcpClient();
    var ar = c.BeginConnect("127.0.0.1", port, null, null);
    if (!ar.AsyncWaitHandle.WaitOne(timeoutMs)) {{ return "ERR: connect timeout"; }}
    c.EndConnect(ar);
    var s = c.GetStream();
    s.ReadTimeout = timeoutMs;
    var bytes = System.Text.Encoding.UTF8.GetBytes(payload + "\n");
    s.Write(bytes, 0, bytes.Length);
    s.Flush();
    var sb = new System.Text.StringBuilder();
    var buf = new byte[4096];
    var sw = System.Diagnostics.Stopwatch.StartNew();
    while (sw.ElapsedMilliseconds < timeoutMs) {{
      if (!s.DataAvailable) {{ System.Threading.Thread.Sleep(60); continue; }}
      int n = s.Read(buf, 0, buf.Length);
      if (n <= 0) break;
      sb.Append(System.Text.Encoding.UTF8.GetString(buf, 0, n));
      if (sb.Length > 20000) break;
    }}
    c.Close();
    return sb.ToString();
  }} catch (System.Exception e) {{ return "ERR: " + e.Message; }}
}}
'@
[HC.Net]::Talk({port}, '{safe}', {int(timeout * 1000)})
"""


def main(argv: list[str]) -> int:
    import tools.vm_guest as vg  # noqa: E402

    op = argv[1] if len(argv) > 1 else "probe"
    out_dir = Path(r"D:\anyworkspace\python\Agent-Rag-MCP-startup\logs")

    if op == "probe":
        port = int(argv[2]) if len(argv) > 2 else 16600
        results = []
        for payload in [f"1 simwarewrapper version", f"2 simwarewrapper system_memory"]:
            ps = build_client_ps(port, payload)
            r = vg.guest_run(ps, timeout=120, interactive=True)
            results.append(f"[{payload}] -> {str(r).strip()}")
            print(results[-1])
        (out_dir / "_hcl_probe.txt").write_text("\n".join(results), encoding="utf-8")
    elif op == "send":
        port = int(argv[2])
        payload = argv[3]
        ps = build_client_ps(port, payload)
        print(vg.guest_run(ps, timeout=120, interactive=True))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
