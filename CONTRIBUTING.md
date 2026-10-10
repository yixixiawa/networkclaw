# 贡献指南

个人毕设项目，但仍按规范协作（也供答辩时展示工程化程度）。

## 分层铁律（改代码前必读）

1. `core/llm_client.py` 是**唯一** LLM 调用出口；端点/密钥/模型名只在
   `core/providers.py`（或 `config/llm.json`）定义，业务模块不得自行拼 HTTP。
2. 所有设备通道（Telnet/串口）必须过 `core/command_guard.py`，不得绕行。
3. 向量库集合名只在 `core/ollama_interface.py` 注册，句柄现取现用。
4. 两个 MCP 服务端**不得定义同名工具**（McpHub 按名路由会串）。

## 提交约定

- 提交用显式路径白名单，`git add` 不加 `-f`；
- 含中文的 `.ps1` 必须带 UTF-8 BOM；
- 模型/密钥/设备历史/技能手册不入库（见 `.gitignore` 注释）。

## 测试与验证

```bash
python -m pytest                                  # 36 项离线测试
python -m core.command_guard                      # 命令分级自检
python -m mcp_tools.client                        # MCP 自检
.venv/Scripts/python.exe -m py_compile main.py core/*.py mcp_tools/*.py tools/*.py
```

## 改了 MCP 工具后

更新 `docs/mcp_tools.md`（文件末尾附生成脚本）。

## 发布

```powershell
.\tools\git_release.ps1 -Tag v1.x          # 清理→构建→提交→打标签（-Push 推送）
python tools\exe_verify.py                 # 出包自检
```
