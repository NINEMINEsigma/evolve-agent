#Requires -Version 5.1
<#
.SYNOPSIS
  Prepare verified Windows x64 desktop runtime resources; never reuse a developer venv.
.DESCRIPTION
  RefreshLock explicitly resolves release dependencies using an internally installed Python.
  StageDev additionally deploys only distributable resources to the repository runtime directory.
  Both locks are intentionally retained after interruption or uncertain tool completion.
  Unique staging attempts are retained for diagnosis; no shared staging tree is recursively deleted.
#>
[CmdletBinding()]
param(
  [switch]$RefreshLock,
  [switch]$StageDev
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Utf8 = New-Object System.Text.UTF8Encoding($false, $true)
$script:ActiveTool = $null
$script:ToolUncertain = $false
$script:ReleaseSafe = $false
$script:Failed = $false
$script:AssetsLease = $null
$script:RuntimeLease = $null
$script:RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')).TrimEnd('\')
$DesktopRoot = Join-Path $script:RepoRoot 'desktop'
$RuntimeRoot = Join-Path $script:RepoRoot 'runtime'
$StagingRoot = Join-Path $DesktopRoot '.runtime-staging'
$SourceRoot = Join-Path $DesktopRoot 'runtime'
$SpecPath = Join-Path $SourceRoot 'release-spec.json'
$InputPath = Join-Path $SourceRoot 'requirements-runtime.in'
$LockPath = Join-Path $SourceRoot 'requirements-win-x64.lock'
$MetaPath = $LockPath + '.meta.json'
$ProbePath = Join-Path $SourceRoot 'probe_environment.py'
$script:AttemptId = [Guid]::NewGuid().ToString()

function Write-Step([string]$Message) {
  Write-Host "[prepare-runtime] $Message" -ForegroundColor Cyan
}

function Assert-ContainedPath([string]$Path, [string]$Root) {
  $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
  $base = [IO.Path]::GetFullPath($Root).TrimEnd('\')
  $cursor = $full
  while ($cursor) {
    if ([string]::Equals($cursor, $base, [StringComparison]::OrdinalIgnoreCase)) { return }
    $parent = [IO.Path]::GetDirectoryName($cursor)
    if ($parent -eq $cursor) { break }
    $cursor = $parent
  }
  throw "Path escapes its managed root: $full (root: $base)"
}

function Assert-NoReparsePoint([string]$Path) {
  # Reject all reparse points, including internal junctions. Component checks, not text prefixes,
  # make lexical containment equivalent to physical containment for accepted managed paths.
  $cursor = [IO.Path]::GetFullPath($Path)
  while ($cursor) {
    try {
      $attributes = [IO.File]::GetAttributes($cursor)
      if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Reparse points are not supported for runtime preparation: $cursor"
      }
    } catch [IO.FileNotFoundException] {
      # A missing leaf is allowed; existing ancestors must still be checked.
    } catch [IO.DirectoryNotFoundException] {
    }
    $parent = [IO.Path]::GetDirectoryName($cursor)
    if ($parent -eq $cursor) { break }
    $cursor = $parent
  }
}

function Assert-ManagedPath([string]$Path, [string]$Root = $script:RepoRoot) {
  Assert-ContainedPath $Path $Root
  Assert-NoReparsePoint $Path
}

function New-ManagedDirectory([string]$Path) {
  Assert-ManagedPath $Path
  [IO.Directory]::CreateDirectory($Path) | Out-Null
  Assert-ManagedPath $Path
}

function Get-Sha256([string]$Path) {
  Assert-ManagedPath $Path
  # Use the same .NET SHA-256 primitive as input hashing, without cmdlet/module discovery.
  $hash = [Security.Cryptography.SHA256]::Create()
  try {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try { $digest = $hash.ComputeHash($stream) }
    finally { $stream.Dispose() }
    return ([BitConverter]::ToString($digest)).Replace('-', '').ToLowerInvariant()
  } finally { $hash.Dispose() }
}

function Get-InputSha256 {
  # Protocol: UTF-8 label, NUL, original file bytes, NUL; concatenate in this exact order.
  $inputs = @(
    @('requirements.txt', (Join-Path $script:RepoRoot 'requirements.txt')),
    @('requirements-runtime.in', $InputPath),
    @('release-spec.json', $SpecPath)
  )
  $hash = [Security.Cryptography.SHA256]::Create()
  try {
    foreach ($inputFile in $inputs) {
      Assert-ManagedPath $inputFile[1]
      $labelBytes = $script:Utf8.GetBytes($inputFile[0])
      $fileBytes = [IO.File]::ReadAllBytes($inputFile[1])
      $nul = [byte[]]@(0)
      [void]$hash.TransformBlock($labelBytes, 0, $labelBytes.Length, $labelBytes, 0)
      [void]$hash.TransformBlock($nul, 0, 1, $nul, 0)
      [void]$hash.TransformBlock($fileBytes, 0, $fileBytes.Length, $fileBytes, 0)
      [void]$hash.TransformBlock($nul, 0, 1, $nul, 0)
    }
    [void]$hash.TransformFinalBlock([byte[]]@(), 0, 0)
    return ([BitConverter]::ToString($hash.Hash)).Replace('-', '').ToLowerInvariant()
  } finally { $hash.Dispose() }
}

function Read-JsonFile([string]$Path) {
  Assert-ManagedPath $Path
  if (-not [IO.File]::Exists($Path)) { throw "Required JSON file is missing: $Path" }
  return ([IO.File]::ReadAllText($Path, $script:Utf8) | ConvertFrom-Json)
}

function Assert-JsonFields($Value, [string[]]$Fields, [string]$Description) {
  if ($null -eq $Value -or $Value -isnot [pscustomobject]) { throw "Invalid $Description object" }
  $actual = @($Value.PSObject.Properties.Name)
  if (@(Compare-Object ($Fields | Sort-Object) ($actual | Sort-Object)).Count -ne 0) {
    throw "Unexpected or missing fields in $Description"
  }
}

function Read-ReleaseSpec([string]$Path) {
  $spec = Read-JsonFile $Path
  Assert-JsonFields $spec @('schemaVersion', 'uvVersion', 'uvAsset', 'pythonRequest', 'pythonVersion', 'platform', 'arch', 'index') 'release specification'
  if ($spec.schemaVersion -isnot [int] -or $spec.schemaVersion -ne 1) { throw 'Unsupported release specification schema' }
  foreach ($field in @('uvVersion', 'uvAsset', 'pythonRequest', 'pythonVersion', 'platform', 'arch', 'index')) {
    if ($spec.$field -isnot [string]) { throw "Release specification field must be a string: $field" }
  }
  if ($spec.uvVersion -cnotmatch '\A[0-9]+\.[0-9]+\.[0-9]+\z' -or $spec.pythonVersion -cnotmatch '\A3\.12\.[0-9]+\z') {
    throw 'Unsupported or malformed toolchain version'
  }
  if ($spec.platform -cne 'win32' -or $spec.arch -cne 'x64' -or $spec.uvAsset -cne 'uv-x86_64-pc-windows-msvc.zip' -or
      $spec.pythonRequest -cne "cpython-$($spec.pythonVersion)-windows-x86_64-none" -or $spec.index -cne 'https://pypi.org/simple') {
    throw 'Release specification must select the supported official Windows x64 toolchain and index'
  }
  return $spec
}

function Write-AtomicBytes([string]$Path, [byte[]]$Bytes) {
  Assert-ManagedPath $Path
  New-ManagedDirectory ([IO.Path]::GetDirectoryName($Path))
  $temporary = $Path + '.' + $script:AttemptId + '.' + [Guid]::NewGuid().ToString() + '.tmp'
  Assert-ManagedPath $temporary
  $stream = New-Object IO.FileStream($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
  try { $stream.Write($Bytes, 0, $Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
  Assert-ManagedPath $Path
  if ([IO.File]::Exists($Path)) { [IO.File]::Replace($temporary, $Path, [NullString]::Value) }
  else { [IO.File]::Move($temporary, $Path) }
}

function Write-AtomicJson([string]$Path, $Value) {
  $json = ($Value | ConvertTo-Json -Depth 8) + "`n"
  Write-AtomicBytes $Path ($script:Utf8.GetBytes($json))
}

function Acquire-Lease([string]$Path) {
  Assert-ManagedPath $Path
  $token = [Guid]::NewGuid().ToString()
  $lease = [ordered]@{
    schemaVersion = 1
    attemptId = $script:AttemptId
    pid = $PID
    installRoot = $script:RepoRoot
    startedAt = [DateTime]::UtcNow.ToString('o')
    token = $token
  }
  try { $stream = New-Object IO.FileStream($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::ReadWrite, [IO.FileShare]::Read) }
  catch { throw "Exclusive lease could not be created: $Path. Exit desktop instances; inspect any interrupted process before manually removing a stale lock. $($_.Exception.Message)" }
  try {
    $bytes = $script:Utf8.GetBytes(($lease | ConvertTo-Json -Compress))
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Flush($true)
  } catch {
    $stream.Dispose()
    throw
  }
  return [pscustomobject]@{ Path = $Path; Token = $token; Stream = $stream }
}

function Release-Lease($Lease) {
  if ($null -eq $Lease) { return }
  Assert-ManagedPath $Lease.Path
  # Read the held handle itself: File.ReadAllText's sharing mode conflicts with a live writer.
  # No delete sharing is granted, so the path cannot be replaced while this handle is held.
  $Lease.Stream.Position = 0
  $reader = New-Object IO.StreamReader($Lease.Stream, $script:Utf8, $true, 1024, $true)
  try { $stored = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
  if ($stored.schemaVersion -ne 1 -or $stored.token -cne $Lease.Token -or $stored.attemptId -cne $script:AttemptId -or
      -not [string]::Equals($stored.installRoot, $script:RepoRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Lease ownership mismatch; leaving lock untouched: $($Lease.Path)"
  }
  $Lease.Stream.Dispose()
  Assert-ManagedPath $Lease.Path
  [IO.File]::Delete($Lease.Path)
}

function ConvertTo-SafeDiagnostic([string]$Text) {
  $safe = [regex]::Replace($Text, '(?i)[a-z][a-z0-9+.-]*://[^\s<>\x22\x27]+', '[redacted-url]')
  $safe = [regex]::Replace($safe, '(?i)[\x22\x27]?(?:proxy-)?authorization[\x22\x27]?\s*[:=]\s*[^\r\n]*', 'authorization=[redacted]')
  return [regex]::Replace($safe, '(?i)[\x22\x27]?(password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret)[\x22\x27]?\s*[:=]\s*(?:\x22(?:\\.|[^\x22\\])*\x22|\x27(?:\\.|[^\x27\\])*\x27|[^\r\n]*)', '$1=[redacted]')
}

function Get-HttpsFile([uri]$Uri, [string]$Destination) {
  Assert-ManagedPath $Destination $StagingRoot
  $current = $Uri
  for ($redirect = 0; $redirect -le 5; $redirect++) {
    if ($current.Scheme -cne 'https' -or
        ($current.DnsSafeHost -cne 'github.com' -and $current.DnsSafeHost -cne 'raw.githubusercontent.com' -and
         $current.DnsSafeHost -cne 'release-assets.githubusercontent.com' -and $current.DnsSafeHost -cne 'objects.githubusercontent.com')) {
      throw 'Download requires HTTPS on an official GitHub distribution host'
    }
    $request = [Net.HttpWebRequest]::Create($current)
    $request.AllowAutoRedirect = $false
    $request.Timeout = 30000
    $request.ReadWriteTimeout = 30000
    $request.UserAgent = 'EvolveAgent-runtime-preparation'
    $response = $null
    try {
      $response = $request.GetResponse()
      $status = [int]$response.StatusCode
      if ($status -in @(301, 302, 303, 307, 308)) {
        if (-not $response.Headers['Location']) { throw 'Download redirect has no Location' }
        $current = New-Object Uri($current, $response.Headers['Location'])
        continue
      }
      if ($status -ne 200) { throw "Official download returned HTTP $status" }
      $source = $response.GetResponseStream()
      $target = New-Object IO.FileStream($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
      try { $source.CopyTo($target); $target.Flush($true) }
      finally { $target.Dispose(); $source.Dispose() }
      if ((Get-Item -LiteralPath $Destination).Length -eq 0) { throw 'Official download is empty' }
      return
    } catch {
      # Preserve the actual network failure reason without signed URLs or proxy credentials.
      $reason = ConvertTo-SafeDiagnostic $_.Exception.Message
      throw "Official HTTPS download failed ($($Uri.Host)$($Uri.AbsolutePath)); $($_.Exception.GetType().Name): $reason"
    } finally { if ($null -ne $response) { $response.Dispose() } }
  }
  throw 'Official download exceeded the redirect limit'
}

function Expand-VerifiedUv([string]$ArchivePath, [string]$Destination) {
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $archive = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
  try {
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $uvEntry = $null
    $total = [long]0
    foreach ($entry in $archive.Entries) {
      $name = $entry.FullName.Replace('\', '/')
      if (-not $name -or $name[0] -eq '/' -or $name.Contains(':')) { throw 'Unsafe path in official uv ZIP' }
      $segments = $name.TrimEnd('/').Split('/')
      foreach ($segment in $segments) {
        if ($segment -in @('', '.', '..') -or $segment -cnotmatch '\A[A-Za-z0-9_.-]+\z' -or $segment.EndsWith('.') -or
            $segment -match '\A(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|\z)') { throw 'Unsafe Windows path in uv ZIP' }
      }
      if (-not $seen.Add($name.TrimEnd('/'))) { throw 'Duplicate path in uv ZIP' }
      $unixType = ($entry.ExternalAttributes -shr 16) -band 0xF000
      if ($unixType -eq 0xA000 -or ($entry.ExternalAttributes -band 0x400) -ne 0) { throw 'Links are forbidden in uv ZIP' }
      $total += $entry.Length
      if ($entry.Length -gt 268435456 -or $total -gt 536870912) { throw 'Official uv ZIP exceeds extraction limits' }
      $candidate = Join-Path $Destination ($name.Replace('/', '\'))
      Assert-ManagedPath $candidate $Destination
      if (-not $name.EndsWith('/') -and $segments[-1] -ceq 'uv.exe') {
        if ($null -ne $uvEntry) { throw 'Multiple uv.exe entries in official ZIP' }
        $uvEntry = $entry
      }
    }
    if ($null -eq $uvEntry -or $uvEntry.Length -eq 0) { throw 'Official ZIP contains no nonempty uv.exe' }
    New-ManagedDirectory $Destination
    $uvPath = Join-Path $Destination 'uv.exe'
    $source = $uvEntry.Open()
    $target = New-Object IO.FileStream($uvPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $source.CopyTo($target); $target.Flush($true) }
    finally { $target.Dispose(); $source.Dispose() }
    return $uvPath
  } finally { $archive.Dispose() }
}

function Get-VerifiedUv($Spec, [string]$AttemptRoot) {
  $downloadRoot = Join-Path $AttemptRoot 'download'
  New-ManagedDirectory $downloadRoot
  $archivePath = Join-Path $downloadRoot $Spec.uvAsset
  $checksumPath = $archivePath + '.sha256'
  $releaseUrl = "https://github.com/astral-sh/uv/releases/download/$($Spec.uvVersion)/$($Spec.uvAsset)"
  Write-Step "Downloading fixed official uv $($Spec.uvVersion) and its archive checksum"
  Get-HttpsFile ([uri]$releaseUrl) $archivePath
  Get-HttpsFile ([uri]($releaseUrl + '.sha256')) $checksumPath
  if ((Get-Item -LiteralPath $checksumPath).Length -gt 4096) { throw 'Malformed official uv checksum file' }
  $checksumText = [IO.File]::ReadAllText($checksumPath, $script:Utf8)
  $pattern = '\A([a-fA-F0-9]{64})(?:[ \t]+\*?' + [regex]::Escape($Spec.uvAsset) + ')?(?:\r?\n)?\z'
  $match = [regex]::Match($checksumText, $pattern)
  if (-not $match.Success) { throw 'Malformed official uv checksum; expected one SHA-256 and optional exact asset name' }
  if ((Get-Sha256 $archivePath) -cne $match.Groups[1].Value.ToLowerInvariant()) { throw 'Official uv archive SHA-256 mismatch' }
  $uvDirectory = Join-Path $AttemptRoot 'runtime\uv'
  $uvPath = Expand-VerifiedUv $archivePath $uvDirectory
  # The release archive need not contain licenses. Both files come from the same fixed tag.
  foreach ($license in @('LICENSE-MIT', 'LICENSE-APACHE')) {
    $licensePath = Join-Path $uvDirectory $license
    Get-HttpsFile ([uri]"https://raw.githubusercontent.com/astral-sh/uv/$($Spec.uvVersion)/$license") $licensePath
    $text = [IO.File]::ReadAllText($licensePath, $script:Utf8)
    if (($license -eq 'LICENSE-MIT' -and $text -notmatch 'Permission is hereby granted') -or
        ($license -eq 'LICENSE-APACHE' -and ($text -notmatch 'Apache License' -or $text -notmatch 'Version 2\.0'))) {
      throw "Missing or invalid official $license"
    }
  }
  return $uvPath
}

function Assert-ManagedTreeHasNoLinks([string]$Path) {
  Assert-ManagedPath $Path
  $pending = New-Object 'System.Collections.Generic.Stack[string]'
  $pending.Push($Path)
  while ($pending.Count -gt 0) {
    foreach ($child in Get-ChildItem -LiteralPath ($pending.Pop()) -Force) {
      Assert-ManagedPath $child.FullName $Path
      if ($child.PSIsContainer) { $pending.Push($child.FullName) }
    }
  }
}

function Test-LexicalContainment([string]$Path, [string]$Root) {
  $cursor = [IO.Path]::GetFullPath($Path).TrimEnd('\')
  $base = [IO.Path]::GetFullPath($Root).TrimEnd('\')
  while ($cursor) {
    if ([string]::Equals($cursor, $base, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    $parent = [IO.Path]::GetDirectoryName($cursor)
    if ($parent -eq $cursor) { break }
    $cursor = $parent
  }
  return $false
}

function New-InstallerEnvironment($Spec) {
  $environment = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([StringComparer]::OrdinalIgnoreCase)
  $pollutedRoots = New-Object 'System.Collections.Generic.List[string]'
  $inherited = [Environment]::GetEnvironmentVariables()
  foreach ($entry in $inherited.GetEnumerator()) {
    $key = [string]$entry.Key
    if ($key -match '^(CONDA_PREFIX(_[0-9]+)?|CONDA_ROOT|_CONDA_ROOT|VIRTUAL_ENV|PYTHONHOME)$' -and
        [IO.Path]::IsPathRooted([string]$entry.Value)) { $pollutedRoots.Add([string]$entry.Value) }
    if ($key -match '^(CONDA_EXE|CONDA_PYTHON_EXE)$' -and [IO.Path]::IsPathRooted([string]$entry.Value)) {
      $condaDirectory = [IO.Path]::GetDirectoryName([string]$entry.Value)
      if ([IO.Path]::GetFileName($condaDirectory) -in @('Scripts', 'condabin')) { $condaDirectory = [IO.Path]::GetDirectoryName($condaDirectory) }
      $pollutedRoots.Add($condaDirectory)
    }
    if ($key -match '^(UV_|PIP_|PYTHON|CONDA|_CONDA|_OLD_VIRTUAL_)' -or $key -ieq 'VIRTUAL_ENV' -or $key -ieq 'VIRTUAL_ENV_PROMPT' -or
        $key -ieq '_CE_CONDA' -or $key -ieq '_CE_M' -or $key -ieq '__PYVENV_LAUNCHER__') { continue }
    $environment[$key] = [string]$entry.Value
  }
  if ($environment.ContainsKey('PATH')) {
    $cleanPath = New-Object 'System.Collections.Generic.List[string]'
    foreach ($component in $environment['PATH'].Split(';')) {
      $candidate = $component.Trim().Trim('"')
      if (-not $candidate -or -not [IO.Path]::IsPathRooted($candidate)) { continue }
      $polluted = [IO.Path]::GetFileName($candidate.TrimEnd('\')) -ieq 'condabin'
      foreach ($root in $pollutedRoots) {
        if (Test-LexicalContainment $candidate $root) { $polluted = $true; break }
      }
      if (-not $polluted) { $cleanPath.Add($component) }
    }
    $environment['PATH'] = $cleanPath -join ';'
  }
  $directories = @{
    UV_PYTHON_INSTALL_DIR = 'python'; UV_CACHE_DIR = 'cache\uv'; UV_PYTHON_CACHE_DIR = 'cache\python'
    UV_CREDENTIALS_DIR = 'credentials'; UV_PYTHON_BIN_DIR = 'uv\python-bin'
    UV_TOOL_DIR = 'tools'; UV_TOOL_BIN_DIR = 'tools\bin'; PIP_CACHE_DIR = 'cache\pip'
    TEMP = 'tmp'; TMP = 'tmp'; TMPDIR = 'tmp'
  }
  foreach ($key in $directories.Keys) {
    $path = Join-Path $RuntimeRoot $directories[$key]
    New-ManagedDirectory $path
    # uv may reuse nested cache/install entries. Check them before a child can follow a junction.
    Assert-ManagedTreeHasNoLinks $path
    $environment[$key] = $path
  }
  $environment['UV_PYTHON_INSTALL_BIN'] = 'false'
  $environment['UV_PYTHON_INSTALL_REGISTRY'] = 'false'
  $environment['UV_MANAGED_PYTHON'] = 'true'
  $environment['UV_NO_CONFIG'] = 'true'
  $environment['UV_HTTP_TIMEOUT'] = '30'
  $environment['UV_HTTP_RETRIES'] = '2'
  $environment['UV_KEYRING_PROVIDER'] = 'disabled'
  $environment['PYTHONNOUSERSITE'] = '1'
  $environment['PYTHONDONTWRITEBYTECODE'] = '1'
  $environment['PYTHONUTF8'] = '1'
  $environment['PYTHONIOENCODING'] = 'utf-8'
  $environment['PIP_CONFIG_FILE'] = 'NUL'
  $environment['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
  $environment['PIP_INDEX_URL'] = $Spec.index
  return ,$environment
}

function ConvertTo-NativeArgument([string]$Value) {
  # Windows CommandLineToArgvW quoting, including backslashes immediately before a quote/end.
  if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
  $quoted = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
  $quoted = [regex]::Replace($quoted, '(\\+)$', '$1$1')
  return '"' + $quoted + '"'
}

function Invoke-OwnedTool([string]$Executable, [string[]]$Arguments, [int]$TimeoutSeconds = 20) {
  Assert-ManagedPath $Executable
  if ($script:ToolUncertain) { throw 'Previous tool completion is uncertain; refusing to start another tool' }
  $info = New-Object Diagnostics.ProcessStartInfo
  $info.FileName = $Executable
  $info.Arguments = (($Arguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' ')
  $info.WorkingDirectory = $AttemptRoot
  $info.UseShellExecute = $false
  $info.CreateNoWindow = $true
  $info.RedirectStandardOutput = $true
  $info.RedirectStandardError = $true
  $info.StandardOutputEncoding = $script:Utf8
  $info.StandardErrorEncoding = $script:Utf8
  $info.EnvironmentVariables.Clear()
  foreach ($key in $InstallerEnvironment.Keys) { $info.EnvironmentVariables[$key] = $InstallerEnvironment[$key] }
  $process = New-Object Diagnostics.Process
  $process.StartInfo = $info
  $script:ActiveTool = $process
  $script:ToolUncertain = $true
  # This flag is only cleared after process exit AND both redirected pipes have completed.
  # An interrupt, timeout, or pipe failure therefore retains both leases for manual diagnosis.
  if (-not $process.Start()) { throw 'Failed to start the verified runtime tool' }
  $stdoutTask = $process.StandardOutput.ReadToEndAsync()
  $stderrTask = $process.StandardError.ReadToEndAsync()
  $watch = [Diagnostics.Stopwatch]::StartNew()
  if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
    throw "Runtime tool exceeded $TimeoutSeconds seconds; locks retained. Inspect and stop the process tree before manually clearing locks."
  }
  $remaining = [Math]::Max(0, ($TimeoutSeconds * 1000) - [int]$watch.ElapsedMilliseconds)
  if (-not [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($stdoutTask, $stderrTask), $remaining)) {
    throw 'Runtime tool pipes did not close within the deadline; locks retained for uncertain child activity'
  }
  $stdout = $stdoutTask.Result
  $stderr = $stderrTask.Result
  # ProcessStartInfo is required for a child-only environment. It does not set PowerShell's
  # LASTEXITCODE itself, so copy the observed native exit code and check it explicitly here.
  $LASTEXITCODE = $process.ExitCode
  $script:ToolUncertain = $false
  $script:ActiveTool = $null
  $process.Dispose()
  if ($stderr) { Write-Host (ConvertTo-SafeDiagnostic $stderr) }
  if ($LASTEXITCODE -ne 0) {
    if ($stdout) { Write-Host (ConvertTo-SafeDiagnostic $stdout) }
    throw "Runtime tool failed with native exit code $LASTEXITCODE; see its diagnostic output above. No fallback interpreter was used."
  }
  return $stdout
}

function Assert-HashedLock([string]$Path) {
  Assert-ManagedPath $Path
  if (-not [IO.File]::Exists($Path) -or (Get-Item -LiteralPath $Path).Length -eq 0) { throw 'Release dependency lock is missing or empty; run runtime:lock explicitly' }
  $statement = ''
  $packages = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
  foreach ($line in [IO.File]::ReadAllLines($Path, $script:Utf8)) {
    $text = ($line -replace '#.*$', '').Trim()
    if (-not $text) { continue }
    $continues = $text.EndsWith('\')
    if ($continues) { $text = $text.Substring(0, $text.Length - 1).TrimEnd() }
    $statement += ' ' + $text
    if ($continues) { continue }
    $hashes = [regex]::Matches($statement, '(?<!\S)--hash=sha256:[a-fA-F0-9]{64}(?!\S)')
    if ($hashes.Count -eq 0) { throw 'Every release requirement must have artifact SHA-256 hashes' }
    $requirement = [regex]::Replace($statement, '(?<!\S)--hash=sha256:[a-fA-F0-9]{64}(?!\S)', '').Trim()
    $match = [regex]::Match($requirement, '\A([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9.!+_-]+(?:\s*;\s*[^\r\n]+)?\z')
    if (-not $match.Success -or $requirement.Contains('--') -or $requirement.Contains('://')) { throw 'Release lock contains an unpinned requirement or unsupported directive' }
    [void]$packages.Add($match.Groups[1].Value)
    $statement = ''
  }
  if ($statement.Trim()) { throw 'Release lock ends with an incomplete continuation' }
  foreach ($package in @('pip', 'setuptools', 'wheel')) {
    if (-not $packages.Contains($package)) { throw "Release lock omits required tooling: $package" }
  }
}

function Assert-RuntimeLock($Spec, [string]$ExpectedInput) {
  if (-not [IO.File]::Exists($LockPath) -or -not [IO.File]::Exists($MetaPath)) {
    throw 'Release lock/meta is missing. A developer must explicitly run runtime:lock before preparing resources.'
  }
  $meta = Read-JsonFile $MetaPath
  Assert-JsonFields $meta @('schemaVersion', 'uvVersion', 'pythonRequest', 'platform', 'arch', 'inputSha256', 'lockSha256') 'release lock metadata'
  if ($meta.schemaVersion -isnot [int] -or $meta.schemaVersion -ne 1 -or $meta.uvVersion -cne $Spec.uvVersion -or
      $meta.pythonRequest -cne $Spec.pythonRequest -or $meta.platform -cne $Spec.platform -or $meta.arch -cne $Spec.arch -or
      $meta.inputSha256 -isnot [string] -or $meta.inputSha256 -cne $ExpectedInput -or
      $meta.lockSha256 -isnot [string] -or $meta.lockSha256 -cnotmatch '\A[a-f0-9]{64}\z' -or
      $meta.lockSha256 -cne (Get-Sha256 $LockPath)) {
    throw 'Release lock/meta is stale or inconsistent. Review inputs and explicitly run runtime:lock; ordinary preparation never resolves dependencies.'
  }
  Assert-HashedLock $LockPath
}

function Update-RuntimeLock($Spec, [string]$UvPath, [string]$ExpectedInput) {
  Write-Step "Installing/locating fixed internal Python $($Spec.pythonVersion) for explicit lock refresh"
  [void](Invoke-OwnedTool $UvPath @('python', 'install', $Spec.pythonRequest, '--no-config', '--managed-python') 1800)
  $found = (Invoke-OwnedTool $UvPath @('python', 'find', $Spec.pythonRequest, '--system', '--managed-python', '--no-python-downloads', '--no-config')).Trim()
  if (-not $found -or $found -match '[\r\n]' -or -not [IO.Path]::IsPathRooted($found) -or $found -notmatch '\A[A-Za-z]:\\') {
    throw 'uv python find did not return exactly one absolute Windows interpreter path'
  }
  $pythonRoot = Join-Path $RuntimeRoot 'python'
  Assert-ManagedPath $found $pythonRoot
  if (-not [IO.File]::Exists($found)) { throw 'Located internal Python executable is missing' }
  $probeText = Invoke-OwnedTool $found @('-I', '-B', $ProbePath, '--mode', 'base', '--expected-version', $Spec.pythonVersion, '--expected-base-root', $pythonRoot)
  if ($script:Utf8.GetByteCount($probeText) -gt 65536 -or $probeText -cnotmatch '\A\s*\{[^\x00]*\}\s*\z') { throw 'Invalid base Python diagnostic response' }
  $probe = $probeText | ConvertFrom-Json
  Assert-JsonFields $probe @('schemaVersion', 'mode', 'ok', 'errorCode', 'executable', 'prefix', 'basePrefix', 'version', 'architecture') 'base Python diagnostic response'
  if ($probe.schemaVersion -ne 1 -or $probe.mode -cne 'base' -or $probe.ok -isnot [bool] -or -not $probe.ok -or
      $null -ne $probe.errorCode -or $probe.version -cne $Spec.pythonVersion -or $probe.architecture -ne 64) { throw 'Internal base Python diagnostic failed' }
  Assert-ManagedPath $probe.executable $pythonRoot
  Assert-ManagedPath $probe.prefix $pythonRoot
  Assert-ManagedPath $probe.basePrefix $pythonRoot
  $temporaryLock = Join-Path $AttemptRoot 'requirements-win-x64.lock'
  Write-Step 'Resolving complete release dependencies and generating artifact hashes (explicit refresh only)'
  [void](Invoke-OwnedTool $UvPath @('pip', 'compile', $InputPath, '--python', $found,
    '--python-version', $Spec.pythonVersion, '--python-platform', 'x86_64-pc-windows-msvc', '--generate-hashes',
    '--output-file', $temporaryLock, '--default-index', $Spec.index, '--keyring-provider', 'disabled',
    '--no-config', '--no-python-downloads', '--managed-python') 1800)
  Assert-HashedLock $temporaryLock
  if ((Get-InputSha256) -cne $ExpectedInput) { throw 'Release inputs changed during lock refresh; refusing to publish' }
  $meta = [ordered]@{
    schemaVersion = 1; uvVersion = $Spec.uvVersion; pythonRequest = $Spec.pythonRequest
    platform = $Spec.platform; arch = $Spec.arch; inputSha256 = $ExpectedInput
    lockSha256 = Get-Sha256 $temporaryLock
  }
  # A pair is not a filesystem transaction. Interrupted publication is detected on the next read.
  Write-AtomicBytes $LockPath ([IO.File]::ReadAllBytes($temporaryLock))
  Write-AtomicJson $MetaPath $meta
  Assert-RuntimeLock $Spec $ExpectedInput
}

function Write-RuntimeRelease($Spec, [string]$ResourceRoot, [string]$ExpectedInput) {
  Assert-RuntimeLock $Spec $ExpectedInput
  if ((Get-InputSha256) -cne $ExpectedInput) { throw 'Release inputs changed during resource preparation' }
  $stagedLock = Join-Path $ResourceRoot 'requirements-win-x64.lock'
  $stagedProbe = Join-Path $ResourceRoot 'support\probe_environment.py'
  Write-AtomicBytes $stagedLock ([IO.File]::ReadAllBytes($LockPath))
  Write-AtomicBytes $stagedProbe ([IO.File]::ReadAllBytes($ProbePath))
  $manifest = [ordered]@{
    schemaVersion = 1; platform = $Spec.platform; arch = $Spec.arch; uvVersion = $Spec.uvVersion
    pythonRequest = $Spec.pythonRequest; pythonVersion = $Spec.pythonVersion
    uvSha256 = Get-Sha256 (Join-Path $ResourceRoot 'uv\uv.exe')
    requirementsInputSha256 = $ExpectedInput
    requirementsLockSha256 = Get-Sha256 $stagedLock
    probeSha256 = Get-Sha256 $stagedProbe
  }
  Write-AtomicJson (Join-Path $ResourceRoot 'release.json') $manifest
}

$ResourceFiles = @('uv\uv.exe', 'uv\LICENSE-MIT', 'uv\LICENSE-APACHE', 'requirements-win-x64.lock', 'support\probe_environment.py', 'release.json')

function Assert-ResourceTree([string]$Path) {
  Assert-ManagedPath $Path
  # Inspect one level at a time, checking links BEFORE descending into a directory.
  $pending = New-Object 'System.Collections.Generic.Stack[string]'
  $pending.Push($Path)
  while ($pending.Count -gt 0) {
    $directory = $pending.Pop()
    foreach ($child in Get-ChildItem -LiteralPath $directory -Force) {
      Assert-ManagedPath $child.FullName $Path
      $relative = $child.FullName.Substring($Path.TrimEnd('\').Length + 1)
      if ($child.PSIsContainer) {
        if ($relative -notin @('uv', 'support')) { throw "Unexpected staging directory: $relative" }
        $pending.Push($child.FullName)
      } elseif ($relative -notin $ResourceFiles) { throw "Unexpected staging file: $relative" }
    }
  }
  foreach ($relative in $ResourceFiles) {
    $file = Join-Path $Path $relative
    Assert-ManagedPath $file $Path
    if (-not [IO.File]::Exists($file) -or (Get-Item -LiteralPath $file).Length -eq 0) { throw "Missing distributable resource: $relative" }
  }
}

function Publish-RuntimeStaging([string]$PreparedRoot) {
  Assert-ResourceTree $PreparedRoot
  $destination = Join-Path $StagingRoot 'runtime'
  Assert-ManagedPath $destination $StagingRoot
  if ([IO.Directory]::Exists($destination)) {
    Assert-ResourceTree $destination
    [IO.Directory]::Move($destination, (Join-Path $AttemptRoot 'previous-runtime'))
  }
  [IO.Directory]::Move($PreparedRoot, $destination)
  Assert-ResourceTree $destination
  return $destination
}

function Deploy-DevelopmentResources([string]$PreparedRoot) {
  Assert-ResourceTree $PreparedRoot
  Write-Step 'Deploying only verified resource files; existing Python, environments, caches and state are untouched'
  # release.json goes last. A partial update produces digest mismatch rather than a false ready state.
  foreach ($relative in $ResourceFiles) {
    $source = Join-Path $PreparedRoot $relative
    $destination = Join-Path $RuntimeRoot $relative
    Write-AtomicBytes $destination ([IO.File]::ReadAllBytes($source))
    if ((Get-Sha256 $destination) -cne (Get-Sha256 $source)) { throw "Development resource digest mismatch: $relative" }
  }
}

$previousTls = [Net.ServicePointManager]::SecurityProtocol
try {
  if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or -not [Environment]::Is64BitOperatingSystem -or
      [Environment]::GetEnvironmentVariable('PROCESSOR_ARCHITECTURE') -notin @('AMD64', 'x86') -or
      ([Environment]::GetEnvironmentVariable('PROCESSOR_ARCHITEW6432') -and [Environment]::GetEnvironmentVariable('PROCESSOR_ARCHITEW6432') -ne 'AMD64')) {
    throw 'Runtime release preparation supports Windows x64 only'
  }
  Assert-ManagedPath $script:RepoRoot
  $ExpectedInput = Get-InputSha256
  $Spec = Read-ReleaseSpec $SpecPath
  if ((Get-InputSha256) -cne $ExpectedInput) { throw 'Release inputs changed while reading the specification' }
  Assert-ManagedPath $ProbePath
  if (-not [IO.File]::Exists($ProbePath)) { throw 'Runtime environment probe source is missing' }
  # Fixed lock order: assets first, then the runtime lease also used by desktop launches.
  $script:AssetsLease = Acquire-Lease (Join-Path $DesktopRoot '.runtime-assets.lock')
  New-ManagedDirectory $RuntimeRoot
  $script:RuntimeLease = Acquire-Lease (Join-Path $RuntimeRoot 'prepare.lock')
  # Confirm create/write/close/delete capability before any network or installer work.
  $writeProbePath = Join-Path $RuntimeRoot ('.write-probe-' + $script:AttemptId)
  Assert-ManagedPath $writeProbePath $RuntimeRoot
  $writeProbeStream = New-Object IO.FileStream($writeProbePath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
  try { $writeProbeStream.WriteByte(0); $writeProbeStream.Flush($true) } finally { $writeProbeStream.Dispose() }
  [IO.File]::Delete($writeProbePath)
  if (-not $RefreshLock) { Assert-RuntimeLock $Spec $ExpectedInput }
  New-ManagedDirectory $StagingRoot
  $AttemptRoot = Join-Path $StagingRoot $script:AttemptId
  New-ManagedDirectory $AttemptRoot
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  $UvPath = Get-VerifiedUv $Spec $AttemptRoot
  if ($RefreshLock) {
    $InstallerEnvironment = New-InstallerEnvironment $Spec
    $versionText = Invoke-OwnedTool $UvPath @('--version', '--no-config')
    if ($versionText -cnotmatch ('\Auv ' + [regex]::Escape($Spec.uvVersion) + '(?:\s|\z)')) { throw 'Verified uv executable reports an unexpected version' }
    Update-RuntimeLock $Spec $UvPath $ExpectedInput
  }
  $resourceRoot = Join-Path $AttemptRoot 'runtime'
  Write-RuntimeRelease $Spec $resourceRoot $ExpectedInput
  $preparedRoot = Publish-RuntimeStaging $resourceRoot
  if ($StageDev) { Deploy-DevelopmentResources $preparedRoot }
  Write-Step "Resources staged at $preparedRoot. This does not constitute application/build validation."
  $script:ReleaseSafe = $true
} catch {
  $script:Failed = $true
  $exception = $_.Exception
  $interrupted = $false
  while ($null -ne $exception) {
    if ($exception -is [Management.Automation.PipelineStoppedException] -or $exception -is [OperationCanceledException]) { $interrupted = $true }
    $exception = $exception.InnerException
  }
  $script:ReleaseSafe = -not $interrupted -and -not $script:ToolUncertain
  Write-Host "[prepare-runtime] ERROR: $($_.Exception.Message)" -ForegroundColor Red
} finally {
  [Net.ServicePointManager]::SecurityProtocol = $previousTls
  if ($script:ReleaseSafe -and -not $script:ToolUncertain) {
    try {
      Release-Lease $script:RuntimeLease
      Release-Lease $script:AssetsLease
    } catch {
      $script:Failed = $true
      Write-Host "[prepare-runtime] Lease cleanup failed: $($_.Exception.Message). Remaining locks require manual inspection." -ForegroundColor Red
    }
  } elseif ($null -ne $script:AssetsLease) {
    Write-Host '[prepare-runtime] Interrupted or uncertain tool activity: locks retained. Confirm all child processes have ended before manually removing the exact lock files.' -ForegroundColor Yellow
  }
}
if ($script:Failed) { exit 1 }
