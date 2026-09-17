#Requires -Version 5.1
<#
.SYNOPSIS
    下载、校验并解压 Blender Windows 便携包（.zip），并创建便携配置目录。

.DESCRIPTION
    在 Windows PowerShell 中运行（不是 Blender 内）。目标目录必须由调用方传入，
    不要依赖写死的盘符。Evolve Agent 示例：

      $dest = Join-Path $env:EVOLVE_WS 'programs'
      powershell -ExecutionPolicy Bypass -File setup_portable.ps1 -Version 4.5.0 -DestDir $dest

    完成后 Blender 位于 <DestDir>\blender-<Version>-windows-x64\blender.exe

.PARAMETER Version
    完整版本号，例如 5.2.2 / 4.5.0

.PARAMETER DestDir
    解压目标目录。必须显式传入。推荐 <workspace>/programs

.PARAMETER Mirror
    下载源 release 目录前缀，默认清华 TUNA 镜像。
    官方源: https://download.blender.org/release
    阿里云: https://mirrors.aliyun.com/blender/release
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [string]$DestDir,

    [string]$Mirror = "https://mirrors.tuna.tsinghua.edu.cn/blender/release"
)

$ErrorActionPreference = "Stop"

$major = ($Version -split '\.')[0..1] -join '.'
$base = "$Mirror/Blender$major"
$zipName = "blender-$Version-windows-x64.zip"
$zipPath = Join-Path $DestDir $zipName

New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

# ---- 1. 下载 ----
if (Test-Path $zipPath) {
    Write-Host "[跳过] 已存在: $zipPath"
} else {
    Write-Host "[下载] $base/$zipName"
    curl.exe -L --fail --retry 3 -o $zipPath "$base/$zipName"
    if ($LASTEXITCODE -ne 0) { throw "下载失败 (curl exit $LASTEXITCODE)，请换 -Mirror 重试" }
}

# 大小合理性检查：便携包约 300-400MB，几十 KB 说明拿到的是 CDN 拦截页
$sizeMB = (Get-Item $zipPath).Length / 1MB
if ($sizeMB -lt 100) { throw "文件只有 $([math]::Round($sizeMB,1)) MB，疑似下载到拦截页。请更换镜像。" }
Write-Host ("[大小] {0:N1} MB" -f $sizeMB)

# ---- 2. MD5 校验 ----
$md5File = Join-Path $DestDir "blender-$Version.md5"
curl.exe -L --fail -o $md5File "$base/blender-$Version.md5"
$expected = (Get-Content $md5File | Where-Object { $_ -match [regex]::Escape($zipName) } | Select-Object -First 1) -split '\s+' | Select-Object -First 1
$actual = (Get-FileHash $zipPath -Algorithm MD5).Hash.ToLower()
Write-Host "[校验] 期望 $expected"
Write-Host "[校验] 实际 $actual"
if ($actual -ne $expected.ToLower()) { throw "MD5 校验失败！文件损坏或被篡改，已终止。" }
Write-Host "[校验] 通过"

# ---- 3. 解压 ----
$extractDir = Join-Path $DestDir "blender-$Version-windows-x64"
if (Test-Path $extractDir) {
    Write-Host "[跳过] 目录已存在: $extractDir"
} else {
    Write-Host "[解压] -> $DestDir"
    Expand-Archive -Path $zipPath -DestinationPath $DestDir
}

# ---- 4. 便携化：配置隔离到 5.x\config ----
$configDir = Join-Path $extractDir "$major\config"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
Write-Host "[便携化] 配置目录: $configDir （此后设置/插件均存于此，不污染 %APPDATA%）"

# ---- 5. 验证 ----
$blender = Join-Path $extractDir "blender.exe"
& $blender --version
Write-Host ""
Write-Host "[完成] blender.exe 路径: $blender"
Write-Host "[测试] & `"$blender`" -b --factory-startup --python-expr `"import bpy; print(bpy.app.version_string)`""
