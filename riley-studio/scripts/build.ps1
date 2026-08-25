# build.ps1 - full stable release pipeline for the Riley Studio suite.
#
#   powershell -ExecutionPolicy Bypass -File riley-studio\scripts\build.ps1
#
# Gates first (a red build never ships), then package + installer.

param([switch]$SkipStabilize)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $PSScriptRoot
$suite = Split-Path -Parent $here
$repo = Split-Path -Parent $suite

if (-not $SkipStabilize) {
    & powershell -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $here "stabilize.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "stabilize failed - fix before packaging" }
}

Write-Output "[build] packaging electron app ..."
& cmd /c "npm --prefix `"$suite\studio`" run package"
if ($LASTEXITCODE -ne 0) { throw "electron-packager failed" }

Write-Output "[build] installer artifact ..."
& powershell -NoProfile -ExecutionPolicy Bypass `
    -File (Join-Path $here "make-installer.ps1")
if ($LASTEXITCODE -ne 0) { throw "installer step failed" }

Write-Output "[build] done."
