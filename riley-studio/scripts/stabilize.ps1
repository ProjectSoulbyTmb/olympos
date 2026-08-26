# stabilize.ps1 - prove the Riley Studio suite is alive; exit code is
# the verdict. Mirrors the house stabilizer contract:
#
#   1 syntax sweep      every studio JS file must parse
#   2 unit tests        node --test (project contract)
#   3 engine gate       python verify_riley_studio.py (offline-safe)
#   4 boot smoke        electron main process boots headless, tray decodes

$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$suite = Split-Path -Parent $here          # riley-studio/
$studio = Join-Path $suite "studio"
Set-Location $suite
$fail = 0

Write-Output "== riley-studio stabilize =="

Write-Output "-- 1/4 syntax sweep"
$bad = 0
Get-ChildItem -Recurse (Join-Path $studio "renderer"),
                      (Join-Path $studio "lib"),
                      (Join-Path $studio "tests") -Filter *.js |
  ForEach-Object {
    node --check $_.FullName 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Output "  SYNTAX FAIL: $($_.FullName)"; $bad++ }
  }
foreach ($f in @("main.js", "preload.js")) {
  node --check (Join-Path $studio $f) 2>$null
  if ($LASTEXITCODE -ne 0) { Write-Output "  SYNTAX FAIL: $f"; $bad++ }
}
if ($bad -gt 0) { $fail = 1 } else { Write-Output "  all files parse" }

Write-Output "-- 2/4 unit tests"
Push-Location $studio
node --test "tests/**/*.test.js" 2>&1 | Select-String "^# (PASS|FAIL)|not ok|^. tests \d|^. pass \d|^. fail \d"
Pop-Location
if ($LASTEXITCODE -ne 0) { Write-Output "  TESTS FAILED"; $fail = 1 }

Write-Output "-- 3/4 engine gate"
python (Join-Path $suite "..\verify_riley_studio.py") 2>&1 |
  Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { Write-Output "  ENGINE GATE FAILED"; $fail = 1 }

Write-Output "-- 4/4 boot smoke"
$env:RILEY_STUDIO_SMOKE = "1"
Push-Location $studio
$out = (& npx electron . 2>&1 | Out-String)
Pop-Location
Remove-Item Env:RILEY_STUDIO_SMOKE -ErrorAction SilentlyContinue
if ($out -match "SMOKE OK") { Write-Output "  shell boots" }
else { Write-Output "  BOOT SMOKE FAILED:"; Write-Output $out; $fail = 1 }

if ($fail -eq 0) { Write-Output "== STABLE ==" } else {
  Write-Output "== UNSTABLE - see above ==" }
exit $fail
