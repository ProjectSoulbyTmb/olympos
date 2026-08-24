# SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
# SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
<#
.SYNOPSIS
  SoulOps automation loop - GAIA watches, scores, alerts and (optionally) auto-fixes.
.EXAMPLE
  .\soulops.ps1                  # one supervised cycle: pulse + fix plan
  .\soulops.ps1 -Execute         # cycle that also applies safe fixes
  .\soulops.ps1 -Install         # register a 15-min Windows scheduled task (current user)
  .\soulops.ps1 -Uninstall       # remove the scheduled task
#>
param(
  [switch]$Execute,
  [switch]$Install,
  [switch]$Uninstall,
  [switch]$Continuous
)

$ErrorActionPreference = 'Continue'
$GaiaDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Log = Join-Path $GaiaDir 'runs\soulops.log'
$TaskName = 'SoulOps-GAIA'

function Write-Log([string]$msg) {
  $line = "{0} {1}" -f (Get-Date -Format o), $msg
  Add-Content -LiteralPath $Log -Value $line -Encoding UTF8
}

if ($Uninstall) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Write-Output "scheduled task '$TaskName' removed"
  exit 0
}

if ($Install) {
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$GaiaDir\soulops.ps1`"$(if ($Execute) { ' -Execute' })" `
    -WorkingDirectory $GaiaDir
  $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration ([TimeSpan]::FromDays(3650))
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description 'GAIA ecosystem health kernel: pulse + safe auto-remediation' | Out-Null
  Write-Output "scheduled task '$TaskName' registered (every 15 min). Logs: $Log"
  exit 0
}

Push-Location $GaiaDir
try {
  if ($Continuous) {
    Write-Log "continuous mode started"
    node gaia.mjs pulse --watch --every 15m $(if ($Execute) { '--fix --execute' }) *>> $Log
  } else {
    $out = node gaia.mjs pulse $(if ($Execute) { '--fix --execute' }) 2>&1
    Write-Log ($out -join ' | ')
    if (-not [Environment]::UserInteractive) { $out | ForEach-Object { "$_" } }
  }
} finally {
  Pop-Location
}
