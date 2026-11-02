#Requires -Version 5.1
<#
.SYNOPSIS
  Copy existing frontend distribution assets for electron-builder; never install Python or build frontend sources.
.DESCRIPTION
  Reads the selected saved configuration to locate the existing workspace. Only its pre-built
  fast_agent_space/frontend/dist and optional build signature are read. The output remains
  desktop/.frontend-staging/frontend, packaged at the existing default frontend location.
  This script is an explicit developer release step; it does not start the application.
#>
[CmdletBinding()]
param([string]$ConfigKey = 'default')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$DesktopRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $DesktopRoot '..'))
$ConfigJson = Join-Path $RepoRoot 'config.json'
$StagingRoot = Join-Path $DesktopRoot '.frontend-staging'

function Assert-NoReparsePoint([string]$Path) {
  $cursor = [IO.Path]::GetFullPath($Path)
  while ($cursor) {
    try {
      if (([IO.File]::GetAttributes($cursor) -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Frontend preparation does not follow reparse points: $cursor"
      }
    } catch [IO.FileNotFoundException] {
    } catch [IO.DirectoryNotFoundException] {
    }
    $parent = [IO.Path]::GetDirectoryName($cursor)
    if ($parent -eq $cursor) { break }
    $cursor = $parent
  }
}

function Test-PathContains([string]$Root, [string]$Path) {
  $base = [IO.Path]::GetFullPath($Root).TrimEnd('\')
  $cursor = [IO.Path]::GetFullPath($Path).TrimEnd('\')
  while ($cursor) {
    if ([string]::Equals($base, $cursor, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    $parent = [IO.Path]::GetDirectoryName($cursor)
    if ($parent -eq $cursor) { break }
    $cursor = $parent
  }
  return $false
}

function Assert-TreeHasNoLinks([string]$Path) {
  Assert-NoReparsePoint $Path
  $pending = New-Object 'System.Collections.Generic.Stack[string]'
  $pending.Push($Path)
  while ($pending.Count -gt 0) {
    foreach ($item in Get-ChildItem -LiteralPath ($pending.Pop()) -Force) {
      Assert-NoReparsePoint $item.FullName
      if ($item.PSIsContainer) { $pending.Push($item.FullName) }
    }
  }
}

try {
  if (-not $ConfigKey) { throw 'A nonempty ConfigKey is required for frontend staging' }
  if (-not [IO.File]::Exists($ConfigJson)) { throw "Saved configuration is missing: $ConfigJson" }
  $raw = [IO.File]::ReadAllText($ConfigJson) | ConvertFrom-Json
  # Saved profile names are dynamic JSON keys, not Python model fields.
  $property = $raw.PSObject.Properties[$ConfigKey]
  if ($null -eq $property) { throw "Saved profile does not exist: $ConfigKey" }
  $profile = $property.Value
  $workspacePath = $profile.__root.__value.workspace_path
  if ($workspacePath -isnot [string] -or -not $workspacePath) { throw 'The selected profile has no workspace_path' }
  if ([IO.Path]::IsPathRooted($workspacePath)) { $workspaceRoot = [IO.Path]::GetFullPath($workspacePath) }
  else { $workspaceRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot $workspacePath)) }
  if ((Test-PathContains $workspaceRoot $StagingRoot) -or (Test-PathContains $StagingRoot $workspaceRoot)) {
    throw 'Frontend output staging and the configured workspace must be disjoint; workspace files are read-only inputs'
  }
  # Preserve the previous release copy location; no runtime repository source is imported/executed.
  $frontendRoot = Join-Path $workspaceRoot 'fast_agent_space\frontend'
  $sourceDist = Join-Path $frontendRoot 'dist'
  $sourceSignature = Join-Path $frontendRoot '.frontend_build_signature.json'
  if (-not [IO.File]::Exists((Join-Path $sourceDist 'index.html'))) {
    throw "Pre-built frontend is missing at $sourceDist. Prepare it using the existing application workflow before packaging."
  }
  Assert-TreeHasNoLinks $sourceDist
  Assert-NoReparsePoint $sourceSignature
  Assert-NoReparsePoint $StagingRoot
  if ([IO.Directory]::Exists($StagingRoot)) {
    Assert-TreeHasNoLinks $StagingRoot
    Remove-Item -LiteralPath $StagingRoot -Recurse -Force
  }
  $destination = Join-Path $StagingRoot 'frontend'
  [IO.Directory]::CreateDirectory($destination) | Out-Null
  Write-Host "[prepare-frontend] Copying existing distribution assets to $destination" -ForegroundColor Cyan
  Copy-Item -LiteralPath $sourceDist -Destination $destination -Recurse -Force
  if ([IO.File]::Exists($sourceSignature)) { Copy-Item -LiteralPath $sourceSignature -Destination $destination -Force }
  Write-Host '[prepare-frontend] Frontend distribution assets staged; no Python installation or frontend build was performed.' -ForegroundColor Green
} catch {
  Write-Host "[prepare-frontend] ERROR: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}
