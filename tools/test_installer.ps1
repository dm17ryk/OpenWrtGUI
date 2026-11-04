<#
.SYNOPSIS
  Install, check and uninstall the built installer silently, in scratch folders under build\.

.NOTES
  CI runs it after tools/build_windows.ps1. It writes HKCU\Software\OpenWrtGUI and the Apps entry
  for a moment, so it refuses to run on a PC where OpenWrtGUI is installed.
#>
param(
    [string]$Installer = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Uninstall = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{3F6C2B7E-9A41-4D2E-8B5C-6E1F0A9D4C27}_is1"
if (Test-Path $Uninstall) { throw "OpenWrtGUI is installed on this PC; run this test in CI or after uninstalling it" }
if (-not $Installer) {
    $Installer = (Get-ChildItem (Join-Path $Root "dist\OpenWrtGUI-Setup-*.exe") | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
}
$Work = Join-Path $Root "build\installer-test"
if (Test-Path $Work) { Remove-Item $Work -Recurse -Force }
New-Item -ItemType Directory $Work | Out-Null

function Install([string]$AppDir, [string]$DataDir) {
    $p = Start-Process -FilePath $Installer -Wait -PassThru -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=$AppDir", "/DATADIR=$DataDir", "/LOG=$AppDir.log"
    )
    return $p.ExitCode
}

function Uninstall([string]$AppDir) {
    $u = Join-Path $AppDir "unins000.exe"
    if (-not (Test-Path $u)) { return }
    Start-Process -FilePath $u -Wait -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" | Out-Null
    # The uninstaller hands over to a copy of itself and returns early.
    for ($i = 0; $i -lt 60 -and (Test-Path (Join-Path $AppDir "OpenWrtGUI.exe")); $i++) { Start-Sleep -Seconds 1 }
}

function Check([bool]$Ok, [string]$What) {
    if (-not $Ok) { throw "installer test failed: $What" }
    Write-Host "    ok: $What"
}

# 1. A data folder shared with other files is refused, and nothing is installed or deleted.
$Shared = Join-Path $Work "shared"
New-Item -ItemType Directory (Join-Path $Shared "logs") | Out-Null
Set-Content (Join-Path $Shared "logs\other-tool.log") "not ours"
$App1 = Join-Path $Work "app-refused"
try {
    $code = Install $App1 $Shared
    Check ($code -eq 7) "a non-empty folder of other files is refused as the data folder (exit $code)"
    Check (-not (Test-Path (Join-Path $App1 "OpenWrtGUI.exe"))) "nothing installed when the data folder is refused"
    Check (Test-Path (Join-Path $Shared "logs\other-tool.log")) "the other files are untouched"
} finally {
    Uninstall $App1
}

# 2. A normal install: files, data-folder setting, a working exe; uninstall removes it all.
$App = Join-Path $Work "app"
$Data = Join-Path $Work "data"
try {
    $code = Install $App $Data
    Check ($code -eq 0) "silent install (exit $code)"
    Check (Test-Path (Join-Path $App "OpenWrtGUI.exe")) "the exe is installed"
    Check ((Get-ItemProperty "HKCU:\Software\OpenWrtGUI").DataDir -eq $Data) "the data folder is recorded"
    $c = Start-Process -FilePath (Join-Path $App "OpenWrtGUI.exe") -Wait -PassThru -ArgumentList @(
        "--self-check", "--simulator", (Join-Path $Root "tests\fixtures\sim"), "--data-dir", (Join-Path $Work "selfcheck")
    )
    Check ($c.ExitCode -eq 0) "the installed app passes its self-check"
} finally {
    Uninstall $App
}
Check (-not (Test-Path (Join-Path $App "OpenWrtGUI.exe"))) "uninstall removes the app"
Check (-not (Test-Path "HKCU:\Software\OpenWrtGUI")) "uninstall removes the data-folder setting"
Check (-not (Test-Path $Uninstall)) "uninstall removes the Apps entry"
Write-Host "installer test passed"
