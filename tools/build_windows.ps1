<#
.SYNOPSIS
  Build OpenWrtGUI for Windows: UI, PyInstaller onedir, self-check, and the installer when Inno Setup is present.

.EXAMPLE
  pwsh -File tools/build_windows.ps1 -Version 0.1.0-dev

.NOTES
  Run it from a checkout inside C:\Essence_SC or D:\Essence_SC on the bench PC (SentinelOne).
  -Version is written into src/openwrtgui/version.py; CI commits nothing, a local run leaves the
  change for you to keep or revert.
#>
param(
    [string]$Version = "0.1.0-dev"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Step([string]$Name, [scriptblock]$Body) {
    Write-Host "==> $Name"
    & $Body
    if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit $LASTEXITCODE)" }
}

# 1. Version
$NumVersion = (uv run python tools/stamp_version.py $Version)
if ($LASTEXITCODE -ne 0) { throw "stamp_version refused $Version" }
Write-Host "==> Version $Version ($NumVersion)"

# 2. UI
Push-Location frontend
try {
    Invoke-Step "npm ci" { npm ci --no-audit --no-fund }
    Invoke-Step "npm run build" { npm run build }
} finally {
    Pop-Location
}

# 3. PyInstaller onedir
Invoke-Step "PyInstaller" {
    uv run --extra build pyinstaller packaging/OpenWrtGUI.spec --noconfirm --distpath dist --workpath build/pyi
}
$Exe = Join-Path $Root "dist\OpenWrtGUI\OpenWrtGUI.exe"
if (-not (Test-Path $Exe)) { throw "PyInstaller produced no $Exe" }
# Dev tools and optional extras that hooks drag in (pydantic.mypy, pygments' image formatter, anyio's
# pytest runner) only make the installer bigger; packaging/OpenWrtGUI.spec excludes them. The
# analysis TOC lists every collected module, also the pure-Python ones inside the PYZ archive.
$Toc = Get-Content (Join-Path $Root "build\pyi\OpenWrtGUI\Analysis-00.toc") -Raw
$Leaked = @("mypy", "PIL", "pytest", "_pytest", "ruff") | Where-Object { $Toc -match "\('$_[.']" }
if ($Leaked) { throw "the bundle contains packages it must not ship: $($Leaked -join ', ')" }

# 4. Self-check of the built exe. It is a windowed app, so wait for it explicitly. Its own data
#    folder keeps the check away from a running OpenWrtGUI and from your real routers and keys.
$CheckData = Join-Path $Root "build\selfcheck-data"
Write-Host "==> Self-check"
$Check = Start-Process -FilePath $Exe -Wait -PassThru -ArgumentList @(
    "--self-check", "--simulator", (Join-Path $Root "tests\fixtures\sim"), "--data-dir", $CheckData
)
if ($Check.ExitCode -ne 0) {
    $Log = Join-Path $CheckData "logs\app.log"
    if (Test-Path $Log) { Get-Content $Log -Tail 30 }
    throw "self-check failed (exit $($Check.ExitCode))"
}
Write-Host "    self-check passed"

# 5. Installer
$Iscc = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "C:\Essence_SC\Inno Setup 7\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 7\ISCC.exe",
    "C:\Program Files\Inno Setup 7\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Essence_SC\scoop\apps\innosetup\current\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($Iscc) {
    Invoke-Step "Inno Setup" { & $Iscc "/DAppVersion=$Version" "/DAppNumVersion=$NumVersion" installer\OpenWrtGUI.iss }
    Write-Host "    dist\OpenWrtGUI-Setup-$Version.exe"
} else {
    Write-Host "Inno Setup not installed: installer is built in CI"
}
