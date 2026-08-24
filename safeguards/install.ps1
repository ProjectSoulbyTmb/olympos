# SAFEGUARDS install - wire the pre-commit gate into this checkout.
# Run:  powershell -ExecutionPolicy Bypass -File safeguards\install.ps1
#
# Preferred activation is the committed hooks directory (portable across
# clones and worktrees, no absolute paths):
#   git config core.hooksPath safeguards/githooks
# This script keeps working for checkouts that prefer .git\hooks.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

# Portable path: point core.hooksPath at the committed shim.
git -C $root config core.hooksPath safeguards/githooks
Write-Host "core.hooksPath -> safeguards/githooks (committed shim)"

# Legacy fallback: also install the absolute-path hook. Note that while
# core.hooksPath is set, git uses ONLY that directory; the file below
# takes over automatically if hooksPath is ever unset.
$hooks = Join-Path $root ".git\hooks"
New-Item -ItemType Directory -Force -Path $hooks | Out-Null
$py = (Get-Command python).Source

$hook = Join-Path $hooks "pre-commit"
@"
#!/bin/sh
# installed by safeguards/install.ps1 - staged-file gates
python "$( ($root -replace '\\', '/') )/safeguards/check.py" --strict
"@ | Set-Content -Path $hook -Encoding ASCII -NoNewline

Write-Host "pre-commit hook installed: $hook"
Write-Host "python resolved to:       $py"
Write-Host "test with:                python safeguards\check.py --strict"
