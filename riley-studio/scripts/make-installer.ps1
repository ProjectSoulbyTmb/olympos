# make-installer.ps1 - zip the packaged app into dist/ + SHA256SUMS.
# Run scripts/build.ps1 (which runs `npm run package` first).

$ErrorActionPreference = "Stop"
$suite = Split-Path -Parent $PSScriptRoot   # riley-studio/
$bundle = Join-Path $suite "studio\release\RileyStudio-win32-x64"
$dist = Join-Path $suite "dist"

if (-not (Test-Path (Join-Path $bundle "RileyStudio.exe"))) {
    Write-Error "no bundle at $bundle - run: npm --prefix studio run package"
}
$pkg = Get-Content (Join-Path $suite "studio\package.json") | ConvertFrom-Json
$version = $pkg.version
New-Item -ItemType Directory -Force -Path $dist | Out-Null

$zip = Join-Path $dist "RileyStudio-v$version-win32-x64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $bundle "*") -DestinationPath $zip `
    -CompressionLevel Optimal

$hashLines = Get-ChildItem $dist -File | ForEach-Object {
    $h = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    "$h  $($_.Name)"
}
Set-Content -Path (Join-Path $dist "SHA256SUMS.txt") `
    -Value ($hashLines -join "`n")

Write-Output "artifact: $zip"
Get-ChildItem $dist -File | ForEach-Object {
    Write-Output ("  {0}  {1:N1} MB" -f $_.Name, ($_.Length / 1MB)) }
