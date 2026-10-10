"""在虚拟机来宾里清空实验设备预置配置（让验收不再假阳性）。

为什么要在来宾侧做
------------------
eNSP 打开的是来宾 `C:\\Users\\yixixiawa\\Desktop\\unzip\\<实验>\\paper.topo`，
设备启动时加载同目录 `paper\\<UUID>\\flash.efz` 里的 `vrpcfg.cfg`——那就是
参考答案本体。改宿主机 `data/ensp_labs/src` 的副本对设备毫无影响，
所以清洗必须落到来宾的真实文件上。

做法：把一段 PowerShell 塞进 vmrun 来宾会话执行（.NET 的 ZipArchive 可直接
读写 zip，不需要在来宾里装 Python）。每个 flash.efz 改写前先备份成 .orig，
随时可用 --restore 还原。

用法：
    python tools/lab_clean_guest.py --dry-run     # 列出将被清洗的设备数
    python tools/lab_clean_guest.py               # 清洗全部实验
    python tools/lab_clean_guest.py --only 03,04  # 只清洗指定实验目录名片段
    python tools/lab_clean_guest.py --restore     # 还原
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import guest_run  # noqa: E402

GUEST_UNZIP = r"C:\Users\yixixiawa\Desktop\unzip"

# 用**黑名单**删除而不是白名单保留：华为出厂配置里有很多我们不认识的默认段，
# 白名单容易误删（实测会丢掉 aaa 之外的安全相关默认项，导致登录异常）。
DROP = (
    r"^\s*(vlan\b|interface\b|ospf\b|rip\b|bgp\b|isis\b|stp\b|mstp\b|"
    r"ip route|route-policy|acl\b|ip ip-prefix|prefix-list|"
    r"port link-type|port trunk|port default|port hybrid|port-isolate|"
    r"ip address|dhcp\b|vrrp\b|eth-trunk|link-aggregation|"
    r"ntp\b|snmp\b|telnet\b|ssh\b|mpls\b|vpn-instance|pim\b|igmp\b|"
    r"qos\b|traffic|mirror|mac-address|sticky|bpdu|loopback|"
    r"static-route|policy-based-route|traffic-policy|arp\b)"
)

_CLEAN_PS = r"""
$ErrorActionPreference = 'Continue'
$root = '__ROOT__'
$drop = '__DROP__'
$restore = $__RESTORE__
$dry = $__DRY__
$only = '__ONLY__'

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$msg = New-Object System.Collections.Generic.List[string]
$changed = 0; $failed = 0; $skipped = 0

function Clean-Text([string]$txt) {
  $blocks = $txt -split '#'
  $keep = New-Object System.Collections.Generic.List[string]
  foreach ($b in $blocks) {
    $t = $b.Trim()
    if ($t -eq '') { continue }
    $first = ($t -split "`n")[0]
    if ($first -match $drop) { continue }
    $keep.Add($t)
  }
  if ($keep.Count -eq 0) { return "#`nreturn`n" }
  return ("#`n" + ($keep -join "`n#`n") + "`n#`nreturn`n")
}

$dirs = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue
foreach ($d in $dirs) {
  if ($only -ne '' -and $d.Name -notlike ('*' + $only + '*')) { continue }
  $flashes = Get-ChildItem -Path (Join-Path $d.FullName 'paper\*\flash.efz') -ErrorAction SilentlyContinue
  if (-not $flashes) { continue }
  $null = $msg.Add(('[' + $d.Name + '] ' + $flashes.Count + ' 台'))
  foreach ($f in $flashes) {
    $bak = $f.FullName + '.orig'
    if ($restore) {
      if (Test-Path -LiteralPath $bak) {
        if (-not $dry) { Copy-Item -LiteralPath $bak -Destination $f.FullName -Force }
        $null = $msg.Add('  还原 ' + $f.Directory.Name); $changed++
      } else { $null = $msg.Add('  无备份 ' + $f.Directory.Name); $skipped++ }
      continue
    }
    if (-not (Test-Path -LiteralPath $bak)) {
      if ($dry) { $null = $msg.Add('  将清洗 ' + $f.Directory.Name); $changed++; continue }
      Copy-Item -LiteralPath $f.FullName -Destination $bak -Force
    }
    try {
      $bytes = [System.IO.File]::ReadAllBytes($f.FullName)
      $zpos = -1
      for ($i = 0; $i -lt $bytes.Length - 3; $i++) {
        if ($bytes[$i] -eq 80 -and $bytes[$i+1] -eq 75 -and $bytes[$i+2] -eq 3 -and $bytes[$i+3] -eq 4) { $zpos = $i; break }
      }
      if ($zpos -lt 0) { $null = $msg.Add('  跳过(非zip) ' + $f.Directory.Name); $skipped++; continue }

      # 必须按 EOCD（PK\x05\x06）算出 zip 的**精确结尾**：
      # eNSP 在 zip 后面还挂了私有尾部，直接把"到文件末尾"整段喂给
      # .NET ZipArchive 会报「中央目录条目数不对应」（实测 30 个文件因此失败）。
      $eocd = -1
      for ($j = $bytes.Length - 22; $j -ge $zpos; $j--) {
        if ($bytes[$j] -eq 80 -and $bytes[$j+1] -eq 75 -and $bytes[$j+2] -eq 5 -and $bytes[$j+3] -eq 6) { $eocd = $j; break }
      }
      if ($eocd -lt 0) { $null = $msg.Add('  跳过(无EOCD) ' + $f.Directory.Name); $skipped++; continue }
      $clen = [System.BitConverter]::ToUInt16($bytes, $eocd + 20)
      $zend = $eocd + 22 + $clen
      if ($zend -gt $bytes.Length) { $zend = $bytes.Length }

      $head = New-Object byte[] $zpos
      [Array]::Copy($bytes, $head, $zpos)
      $tailLen = $bytes.Length - $zend
      $tail = New-Object byte[] $tailLen
      if ($tailLen -gt 0) { [Array]::Copy($bytes, $zend, $tail, 0, $tailLen) }
      $zlen = $zend - $zpos
      $zbytes = New-Object byte[] $zlen
      [Array]::Copy($bytes, $zpos, $zbytes, 0, $zlen)

      $ms = New-Object System.IO.MemoryStream
      $ms.Write($zbytes, 0, $zbytes.Length); $ms.Position = 0
      $za = New-Object System.IO.Compression.ZipArchive($ms, [System.IO.Compression.ZipArchiveMode]::Update)
      $entry = $za.GetEntry('vrpcfg.cfg')
      if (-not $entry) { $za.Dispose(); $null = $msg.Add('  跳过(无cfg) ' + $f.Directory.Name); $skipped++; continue }
      $sr = New-Object System.IO.StreamReader($entry.Open(), [System.Text.Encoding]::UTF8)
      $txt = $sr.ReadToEnd(); $sr.Close()
      $entry.Delete()
      $ne = $za.CreateEntry('vrpcfg.cfg')
      $sw = New-Object System.IO.StreamWriter($ne.Open(), [System.Text.Encoding]::UTF8)
      $sw.Write((Clean-Text $txt)); $sw.Close()
      $za.Dispose()

      $out = New-Object System.Collections.Generic.List[byte]
      $out.AddRange($head); $out.AddRange($ms.ToArray())
      if ($tailLen -gt 0) { $out.AddRange($tail) }
      [System.IO.File]::WriteAllBytes($f.FullName, $out.ToArray())
      $null = $msg.Add('  已清洗 ' + $f.Directory.Name); $changed++
    } catch {
      $null = $msg.Add('  失败 ' + $f.Directory.Name + ' : ' + $_.Exception.Message); $failed++
    }
  }
}
$msg.Add(('完成: 处理 ' + $changed + ' 失败 ' + $failed + ' 跳过 ' + $skipped))
$msg -join "`n"
""".replace("__ROOT__", GUEST_UNZIP)


def run(restore: bool = False, dry: bool = False, only: str = "") -> str:
    ps = _CLEAN_PS
    ps = ps.replace("__DROP__", DROP)
    ps = ps.replace("$__RESTORE__", "$true" if restore else "$false")
    ps = ps.replace("$__DRY__", "$true" if dry else "$false")
    ps = ps.replace("__ONLY__", only.replace("'", "''"))
    return guest_run(ps, timeout=900)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="来宾侧清空实验设备预置配置")
    ap.add_argument("--only", default="", help="只处理目录名含该片段的实验")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv[1:])
    print(run(restore=a.restore, dry=a.dry_run, only=a.only))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
