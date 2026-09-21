# NetworkClaw 自动打包 + 发布到 git（清理 → 构建 → 提交产物 → 打 tag）
#
# 用法：
#   .\tools\git_release.ps1 -Tag v1.0                 # 打包并发布 v1.0（本次会用到的）
#   .\tools\git_release.ps1 -Tag v1.1 -Push           # 构建 + 提交 + 打 tag + 推送（需已配 remote）
#   .\tools\git_release.ps1 -Tag v1.0 -SkipBuild      # 复用已有产物，只提交与打 tag
#   .\tools\git_release.ps1                            # 只打包并提交，不打 tag
#
# 设计要点：
#   * exe 体积大（~270MB），提交二进制会让仓库膨胀，所以**只在发布时**提交产物：
#     日常提交走普通 git 流程，本脚本负责「发布这一刻」的完整动作。
#   * 幂等：重复执行不会产生空提交；tag 已存在时给出明确提示而不是静默覆盖。
#   * 产物入库前先清掉运行痕迹（dist 里的 logs/、data/、__pycache__ 等）。
param(
    [string]$Tag = "",
    [string]$Message = "",
    [switch]$SkipBuild,
    [switch]$Push,
    [switch]$Force,
    [switch]$KeepBuild   # 保留 build/ 中间目录（默认清理，避免污染仓库）
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Info($msg) { Write-Host "==> $msg" }
function Fail($msg) { Write-Host "!!  $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path (Join-Path $root ".git"))) { Fail "当前目录不是 git 仓库：$root" }

$exeRel = "dist\NetworkClaw\NetworkClaw.exe"
$oneFileRel = "dist\NetworkClaw.exe"

# 期望被纳入提交的路径（明确列出，避免误提交密钥/模型/运行数据）
$trackPaths = @(
    "launcher.py", "main.py", "NetworkClaw.spec", "build_exe.ps1",
    "README.md", "requirements.txt", ".gitignore", ".gitattributes",
    "core", "gui", "mcp_tools", "tools", "docs", "assets", "knowledge",
    "config/llm.example.json", ".githooks",
    # 向量库与索引指纹一向入库（体积 ~4MB，便于 clone 后直接检索）
    "data/Rag_data", "data/index_state.json"
)

# ---------------------------------------------------------------- 1) 清理
Info "步骤 1/5：清理临时产物"
$junk = @()
$junk += Get-ChildItem -Path $root -File -Filter "_*" -ErrorAction SilentlyContinue
foreach ($d in @("build", "core\__pycache__", "gui\__pycache__", "mcp_tools\__pycache__",
                "tools\__pycache__", "__pycache__", "dist\NetworkClaw\logs", "dist\NetworkClaw\data")) {
    $full = Join-Path $root $d
    if (Test-Path $full) { $junk += Get-Item $full }
}
$removed = 0
$blocked = @()
foreach ($item in $junk) {
    # 逐项 try/catch：某些受限环境（沙箱回收站不可用）会拒绝删除，
    # 这种情况只提示、不中断发布流程 —— build/ 之类留着也不影响打包与提交。
    try {
        Remove-Item -LiteralPath $item.FullName -Recurse -Force -ErrorAction Stop
        $removed++
    } catch {
        $blocked += $item.Name
    }
}
Info ("已清理 {0} 项；{1} 项被环境拒绝删除（不影响发布）" -f $removed, $blocked.Count)
if ($blocked.Count -gt 0) { Write-Host ("    未删除：{0}" -f ($blocked -join ", ")) }

# ---------------------------------------------------------------- 2) 构建
Info "步骤 2/5：构建 exe"
if ($SkipBuild) {
    Write-Host "    跳过（-SkipBuild）"
} else {
    & powershell -ExecutionPolicy Bypass -File (Join-Path $root "build_exe.ps1") -SkipIcon:$false
    if ($LASTEXITCODE -ne 0) { Fail "构建失败，详见上方输出" }
}
if (-not (Test-Path (Join-Path $root $exeRel))) { Fail "未找到产物 $exeRel，构建可能失败" }

# 产物体积一览
$distDir = Join-Path $root "dist\NetworkClaw"
if (Test-Path $distDir) {
    $sz = (Get-ChildItem $distDir -Recurse -File | Measure-Object Length -Sum).Sum
    Info ("产物：{0}（{1:N1} MB）" -f $exeRel, ($sz / 1MB))
}

# ---------------------------------------------------------------- 3) 提交
Info "步骤 3/5：纳入版本控制（源码 + 产物）"
foreach ($p in $trackPaths) {
    if (Test-Path (Join-Path $root $p)) { git add -- $p }
}
# dist 下的运行痕迹（logs/、data/sessions.json）由 .gitignore 排除，
# 所以这里**不能**用 -f：-f 会连被忽略的文件一起提交，把日志与会话记录带进仓库。
git add -- "dist/NetworkClaw"
if ($LASTEXITCODE -ne 0) {
    # 兜底：万一 dist 被忽略规则命中，再强制加入产物本身（仍受子目录忽略规则约束）
    Write-Host "    常规 add 未生效，改用强制方式加入产物"
    git add -f -- "dist/NetworkClaw"
}
if (Test-Path (Join-Path $root $oneFileRel)) { git add -f -- "dist/NetworkClaw.exe" }

$staged = git diff --cached --name-only
if (-not $staged) {
    Info "没有需要提交的改动（工作区已是最新）"
} else {
    $count = ($staged | Measure-Object).Count
    $title = if ($Message) { $Message } else { if ($Tag) { "release($Tag)：打包产物入库" } else { "chore：打包产物入库" } }
    Info ("暂存 {0} 个文件，提交：{1}" -f $count, $title)
    git commit -q -m $title
    if ($LASTEXITCODE -ne 0) { Fail "提交失败" }
    git log --oneline -1
}

# ---------------------------------------------------------------- 4) tag
Info "步骤 4/5：打标签"
if (-not $Tag) {
    Write-Host "    未指定 -Tag，跳过"
} elseif (git tag -l $Tag) {
    # 注意：这里不能用 `(git tag -l $Tag) -ne ""` 判断 —— 没有标签时返回 $null，
    # 而 PowerShell 里 $null -ne "" 为真，会把「不存在」误判成「已存在」。
    if ($Force) {
        $forceMsg = if ($Message) { $Message } else { "NetworkClaw $Tag" }
        git tag -f -a $Tag -m $forceMsg
        Write-Host "    已强制覆盖标签 $Tag"
    } else {
        Write-Host "    标签 $Tag 已存在，未改动（如需覆盖请加 -Force）"
    }
} else {
    $msg = if ($Message) { $Message } else { "NetworkClaw $Tag：桌面端 + 打包为 exe" }
    git tag -a $Tag -m $msg
    if ($LASTEXITCODE -ne 0) { Fail "打标签失败" }
    Write-Host "    已创建标签 $Tag"
}

# ---------------------------------------------------------------- 5) 推送
Info "步骤 5/5：推送"
$remotes = git remote
if (-not $remotes) {
    Write-Host "    仓库还没有配置远端（git remote add origin <url>），本地已完成提交与打标签"
    Write-Host "    配置远端后可用：git push -u origin main --tags"
} elseif ($Push) {
    git push origin HEAD
    if ($LASTEXITCODE -ne 0) { Fail "推送分支失败" }
    if ($Tag) { git push origin $Tag }
    Write-Host "    已推送分支与标签"
} else {
    Write-Host "    未加 -Push，未推送。手动推送：git push origin main --tags"
}

Write-Host ""
Write-Host "完成。查看：git log --oneline -3 / git tag -l / git show --stat $Tag"
