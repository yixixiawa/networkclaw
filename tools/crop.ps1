param(
  [Parameter(Mandatory=$true)][string]$Src,
  [Parameter(Mandatory=$true)][int]$X,
  [Parameter(Mandatory=$true)][int]$Y,
  [Parameter(Mandatory=$true)][int]$W,
  [Parameter(Mandatory=$true)][int]$H,
  [Parameter(Mandatory=$true)][string]$Out,
  [int]$Zoom = 2
)
Add-Type -AssemblyName System.Drawing
# 相对路径一律按项目根解析：PowerShell 里 [Environment]::CurrentDirectory 不会跟着
# Set-Location 走，.NET 的 Save() 用相对路径会落到别处
$root = Split-Path $PSScriptRoot -Parent
if (-not [System.IO.Path]::IsPathRooted($Src)) { $Src = Join-Path $root $Src }
if (-not [System.IO.Path]::IsPathRooted($Out)) { $Out = Join-Path $root $Out }
$img = [System.Drawing.Image]::FromFile((Resolve-Path $Src))
$rect = New-Object System.Drawing.Rectangle($X, $Y, [Math]::Min($W, $img.Width - $X), [Math]::Min($H, $img.Height - $Y))
$bmp = New-Object System.Drawing.Bitmap($rect.Width * $Zoom, $rect.Height * $Zoom)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
$g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
$g.DrawImage($img, (New-Object System.Drawing.Rectangle(0, 0, $bmp.Width, $bmp.Height)), $rect, [System.Drawing.GraphicsUnit]::Pixel)
$g.Dispose()
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose(); $img.Dispose()
Write-Output "crop -> $Out  (offset $X,$Y zoom ${Zoom}x)"
