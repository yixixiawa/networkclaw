# NetworkClaw 打包脚本（Windows / PowerShell）
# 用法：
#   .\build_exe.ps1              # 目录形态（推荐）：dist\NetworkClaw\NetworkClaw.exe
#   .\build_exe.ps1 -OneFile     # 单文件形态（启动慢，MCP 子进程每次都要重新解压）
#   .\build_exe.ps1 -SkipIcon    # 跳过图标重新生成
param(
    [switch]$OneFile,
    [switch]$SkipIcon
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "未找到虚拟环境解释器：$py（先运行 pip install pyinstaller）" }

Set-Location $root

# 1) 图标（脚本化生成，改 tools/make_icon.py 后重跑即可）
if (-not $SkipIcon) {
    Write-Host "==> 生成图标 assets/networkclaw.ico"
    & $py tools\make_icon.py
}

# 2) 语法自检：打包前先确认所有入口模块都能编译，避免「打包成功但内容是坏的」
Write-Host "==> 语法自检（py_compile）"
& $py -m py_compile launcher.py main.py `
    (Get-ChildItem core\*.py | ForEach-Object { $_.FullName }) `
    (Get-ChildItem mcp_tools\*.py | ForEach-Object { $_.FullName }) `
    (Get-ChildItem gui\*.py | ForEach-Object { $_.FullName })
if ($LASTEXITCODE -ne 0) { Write-Error "语法自检未通过，已中止打包" }

# 3) PyInstaller 构建
if ($OneFile) { $env:NETWORKCLAW_ONEFILE = "1" } else { Remove-Item Env:NETWORKCLAW_ONEFILE -ErrorAction SilentlyContinue }
Write-Host "==> PyInstaller 构建（$(if ($OneFile) { '单文件' } else { '目录形态' })）"
& $py -m PyInstaller NetworkClaw.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller 构建失败，详见上方日志" }

# 4) 结果
$out = if ($OneFile) { "dist\NetworkClaw.exe" } else { "dist\NetworkClaw\NetworkClaw.exe" }
Write-Host "==> 完成：$out"
if (Test-Path $out) {
    $size = (Get-Item $out).Length
    if (-not $OneFile) {
        $size = (Get-ChildItem "dist\NetworkClaw" -Recurse -File | Measure-Object Length -Sum).Sum
    }
    Write-Host ("    总大小：{0:N1} MB" -f ($size / 1MB))
    Write-Host "    提醒：把 models\Qwen3.5-9B-Q4_K_M.gguf、mmproj-BF16.gguf 与 llama-server.exe 放到 exe 同目录（或用环境变量 NETWORKCLAW_LLAMA_SERVER 指路）"
}
