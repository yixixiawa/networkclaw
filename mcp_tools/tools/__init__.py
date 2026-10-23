"""单工具模块包：一个文件 = 一个 MCP 工具。

为什么这样拆：
    服务端文件（mcp_tools/*_server.py）原本一个文件里塞了 2~6 个工具，改一个工具
    要在一堆无关代码里找位置，评审时也很难说清「这个工具到底改了哪些行」。
    按「一个作用点一个文件」拆开后：
      · 每个文件的职责单一，改动面一目了然；
      · 新增工具 = 新增一个文件 + 在注册中心 add 一行，不会碰到别人的代码；
      · 服务端文件退化为纯注册中心（建 FastMCP 实例 + 装配工具），不再含业务逻辑。

命名约定：
    文件名为工具名（snake_case），与 MCP 工具名一一对应，例如
    `tools/exec_telnet_command.py` 里的 `exec_telnet_command`。

与服务端的关系：
    `mcp_tools/telnet_server.py` 等仍然存在，是**服务端入口**（被 client 以 stdio
    拉起），但它只做两件事：`mcp = FastMCP(...)`、`mcp.tool(fn)` 逐个装配。
    工具本身不持有 mcp 实例——这样工具文件可以被单元测试直接 import 调用，
    不必启动 MCP 运行时就。
"""
