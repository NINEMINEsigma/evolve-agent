#Requires -Version 5.1
<#
.SYNOPSIS
  Prepare Python environment into ../venv/ for electron-builder packaging.
.DESCRIPTION
  Supports two venv layouts:
    A. Standard venv (python -m venv venv) - python.exe at venv/Scripts/
    B. Embedded Python - python.exe at venv/ root

  Flow:
    1. Detect if ../venv/ already exists and is usable (both layouts)
    2. If exists -> install/update dependencies, skip creation
    3. If not exists -> download embedded Python, extract to ../venv/, enable pip
    4. Install dependencies from ../requirements.txt
.NOTES
  main.js detectPythonPath() covers both layouts:
    venv/Scripts/python.exe -> venv/python.exe -> venv/bin/python -> system 'python'
#>

$ErrorActionPreference = 'Stop'

# -- Constants --

$RepoRoot    = Resolve-Path "$PSScriptRoot\..\.."
$VenvDir     = Join-Path $RepoRoot 'venv'
$ReqFile     = Join-Path $RepoRoot 'requirements.txt'

$PyVersion   = '3.12.8'
$PyArch      = 'amd64'
$EmbedUrl    = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-$PyArch.zip"
$GetPipUrl   = 'https://bootstrap.pypa.io/get-pip.py'

$TempDir     = Join-Path $env:TEMP "evolve-embed-$(Get-Random)"

# -- Helpers --

function Write-Step($msg) { Write-Host "[prepare-embed] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "[prepare-embed] OK: $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "[prepare-embed] WARN: $msg" -ForegroundColor Yellow }

# Find python.exe in venv, supporting both layouts
function Find-VenvPython {
  $candidates = @(
    (Join-Path (Join-Path $VenvDir 'Scripts') 'python.exe'),
    (Join-Path $VenvDir 'python.exe')
  )
  foreach ($p in $candidates) {
    if (Test-Path $p) { return $p }
  }
  return $null
}

# Find site-packages directory
function Find-SitePackages {
  $p = Join-Path (Join-Path $VenvDir 'Lib') 'site-packages'
  if (Test-Path $p) { return $p }
  return $null
}

# -- Main --

try {
  $PythonExe = Find-VenvPython
  $SitePkgs  = Find-SitePackages

  # 1. Existing venv -> install deps and exit
  if ($PythonExe -and $SitePkgs) {
    Write-Step "venv/ found: $PythonExe"
    Write-Step "Installing/updating dependencies..."
    & $PythonExe -m pip install --upgrade pip --quiet
    & $PythonExe -m pip install -r $ReqFile --quiet
    Write-Ok "Dependencies installed"
    exit 0
  }

  # 2. No venv -> download embedded Python
  Write-Step "venv/ not found or incomplete, preparing embedded Python"
  Write-Step "Target: $VenvDir"
  Write-Step "Python: $PyVersion ($PyArch)"

  if (Test-Path $VenvDir) {
    Write-Step "Cleaning old venv/ directory"
    Remove-Item $VenvDir -Recurse -Force
  }
  New-Item -ItemType Directory -Path $VenvDir -Force | Out-Null
  New-Item -ItemType Directory -Path $TempDir -Force | Out-Null

  # 2a. Download embedded Python
  $ZipPath = Join-Path $TempDir 'python-embed.zip'
  Write-Step "Downloading $EmbedUrl"
  Invoke-WebRequest -Uri $EmbedUrl -OutFile $ZipPath -UseBasicParsing

  # 2b. Extract to venv/
  Write-Step "Extracting to $VenvDir"
  Expand-Archive -Path $ZipPath -DestinationPath $VenvDir -Force

  # 2c. Enable site-packages (uncomment 'import site' in python._pth)
  $PthFile = Get-ChildItem -Path $VenvDir -Filter 'python*._pth' | Select-Object -First 1
  if ($PthFile) {
    Write-Step "Enabling site-packages: $($PthFile.Name)"
    $content = Get-Content $PthFile.FullName -Raw
    $content = $content -replace '#import site', 'import site'
    if ($content -notmatch 'Lib/site-packages') {
      $content += "`nLib/site-packages`n"
    }
    Set-Content -Path $PthFile.FullName -Value $content -NoNewline
  }

  # 2d. Download and run get-pip.py
  $GetPipPath = Join-Path $TempDir 'get-pip.py'
  Write-Step "Downloading $GetPipUrl"
  Invoke-WebRequest -Uri $GetPipUrl -OutFile $GetPipPath -UseBasicParsing

  $EmbedPythonExe = Join-Path $VenvDir 'python.exe'
  Write-Step "Installing pip"
  & $EmbedPythonExe $GetPipPath --quiet --no-warn-script-location

  # 2e. Install project dependencies
  if (Test-Path $ReqFile) {
    Write-Step "Installing dependencies: $ReqFile"
    & $EmbedPythonExe -m pip install --upgrade pip --quiet
    & $EmbedPythonExe -m pip install -r $ReqFile --quiet
  } else {
    Write-Warn2 "requirements.txt not found, skipping dependency installation"
  }

  # 2f. Verify
  if (-not (Test-Path $EmbedPythonExe)) {
    throw "python.exe not found, embedded Python preparation failed"
  }

  $Version = & $EmbedPythonExe --version 2>&1
  Write-Ok "Embedded Python ready: $Version"

} catch {
  Write-Host '[prepare-embed] ERROR:' $_ -ForegroundColor Red
  exit 1
} finally {
  if (Test-Path $TempDir) {
    Remove-Item $TempDir -Recurse -Force -ErrorAction SilentlyContinue
  }
}