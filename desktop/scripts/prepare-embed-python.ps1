#Requires -Version 5.1
<#
.SYNOPSIS
  Prepare Python environment + pre-built frontend for electron-builder packaging.
.DESCRIPTION
  Phase 1: Python venv
    Supports two venv layouts:
      A. Standard venv (python -m venv venv) - python.exe at venv/Scripts/
      B. Embedded Python - python.exe at venv/ root

  Phase 2: Frontend pre-build copy
    Copies dist/ and .frontend_build_signature.json from a workspace
    run into desktop/.frontend-staging/frontend/ so electron-builder can
    package them into the install directory's workspace/fast_agent_space/frontend/.

    Because origin_agent/frontend/ has NO dist/, fouce_init's
    shutil.copytree(origin_agent, fast, dirs_exist_ok=True) will NOT
    overwrite the pre-placed dist/ in workspace/fast_agent_space/frontend/.

    Usage: prepare-embed-python.ps1 [--config-key <key>]
    When --config-key is provided, reads config.json to locate
    workspace_path, then copies:
      <workspace>/fast_agent_space/frontend/dist                        -> .frontend-staging/frontend/dist
      <workspace>/fast_agent_space/frontend/.frontend_build_signature.json -> .frontend-staging/frontend/
    If --config-key is omitted, frontend copy is skipped.
.NOTES
  main.js detectPythonPath() covers both venv layouts:
    venv/Scripts/python.exe -> venv/python.exe -> venv/bin/python -> system 'python'
#>

param(
  [string]$ConfigKey = ""
)

$ErrorActionPreference = 'Stop'

# -- Constants --

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopDir  = Split-Path -Parent $ScriptDir
$RepoRoot    = Resolve-Path "$DesktopDir\.."
$VenvDir     = Join-Path $RepoRoot 'venv'
$ReqFile     = Join-Path $RepoRoot 'requirements.txt'
$ConfigJson  = Join-Path $RepoRoot 'config.json'

# Staging area for pre-built frontend (inside desktop/, gitignored)
$StagingDir  = Join-Path $DesktopDir '.frontend-staging'

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

# -- Phase 2: Frontend pre-build copy --

function Copy-FrontendPrebuild {
  if (-not $ConfigKey) {
    Write-Warn2 "No --config-key provided, skipping frontend pre-build copy"
    return
  }

  if (-not (Test-Path $ConfigJson)) {
    throw "config.json not found at $ConfigJson"
  }

  $raw = Get-Content $ConfigJson -Raw | ConvertFrom-Json
  $profile = $raw.$ConfigKey
  if (-not $profile) {
    throw "Profile '$ConfigKey' not found in config.json"
  }

  $workspacePath = $profile.__root.__value.workspace_path
  if (-not $workspacePath) {
    throw "workspace_path not set in profile '$ConfigKey'"
  }

  # Resolve relative to repo root
  $wsDir = Join-Path $RepoRoot $workspacePath
  if (-not (Test-Path $wsDir)) {
    throw "Workspace directory not found: $wsDir"
  }

  $fastFrontend = Join-Path $wsDir 'fast_agent_space\frontend'
  $srcDist      = Join-Path $fastFrontend 'dist'
  $srcSig       = Join-Path $fastFrontend '.frontend_build_signature.json'

  if (-not (Test-Path (Join-Path $srcDist 'index.html'))) {
    throw "Pre-built dist not found at $srcDist - run the agent at least once with this profile before building"
  }

  # Clean and recreate staging
  if (Test-Path $StagingDir) { Remove-Item $StagingDir -Recurse -Force }
  $stagingFrontend = Join-Path $StagingDir 'frontend'
  New-Item -ItemType Directory -Path $stagingFrontend -Force | Out-Null

  Write-Step "Copying pre-built frontend to staging: $stagingFrontend"
  Copy-Item -Path $srcDist -Destination $stagingFrontend -Recurse -Force

  if (Test-Path $srcSig) {
    Copy-Item -Path $srcSig -Destination $stagingFrontend -Force
  }

  Write-Ok "Frontend pre-build staged at $stagingFrontend"
}

# -- Phase 1: Python venv --

try {
  # Frontend pre-build copy (before packaging)
  Copy-FrontendPrebuild

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