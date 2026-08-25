# REPO HOME GUARD - PowerShell shim (install into your profile).
#
# Operator policy 2026-08-24: local repositories live under D:\ only.
# This shim intercepts the repo-minting git verbs at the door:
#   clone / init / worktree add / submodule add
# and refuses any destination outside D:\. Everything else passes
# through to real git untouched. Canonical policy logic + audits:
#   python safeguards/repo_home_guard.py   (in the olympos checkout)
#
# Install (CurrentUserAllHosts):
#   . "D:\THOTH\safeguards\repo_home_profile.ps1"
# Revoke: delete that line from $PROFILE (policy is operator-owned).

$script:RepoHomeRealGit = Get-Command git -CommandType Application `
    -ErrorAction SilentlyContinue | Select-Object -First 1

function Get-RepoHomePolicy {
    "allowed local repo home(s): D:\  (operator-set 2026-08-24; " +
    "revoke via profile line or safeguards/repo_home_guard.py)"
}

function Test-RepoHomePath {
    param([Parameter(Mandatory)][string]$Path)
    $p = [System.IO.Path]::GetFullPath($Path).ToLowerInvariant()
    if ($p -like '\\*') { return $false }          # UNC: not localside
    $root = 'd:\'
    return ($p -eq $root -or $p.StartsWith($root))
}

function _RepoHome-Destinations {
    # Mirror of repo_home_guard.py destinations(): candidates this
    # invocation would mint on disk. [] = nothing to judge.
    param([string[]]$GitArgs)
    $dests = @()
    $cwdHint = $null
    $i = 0
    while ($i -lt $GitArgs.Count) {
        if ($GitArgs[$i] -eq '-C') {
            if ($i + 1 -lt $GitArgs.Count) { $cwdHint = $GitArgs[$i + 1] }
            $i += 2; continue
        }
        if ($GitArgs[$i] -match '^-' ) { $i += 1; continue }
        break
    }
    if ($i -ge $GitArgs.Count) { return $dests }
    $verb = $GitArgs[$i].ToLower()
    # NB: plain range 1..0 enumerates DOWN in PS (@(1,0)) - guard it
    $rest = if ($i + 1 -lt $GitArgs.Count) {
        @($GitArgs[($i + 1)..($GitArgs.Count - 1)])
    } else { @() }
    $base = if ($cwdHint) { $cwdHint } else { (Get-Location).Path }
    switch ($verb) {
        'clone' {
            $pos = @($rest | Where-Object { $_ -notmatch '^-' })
            if ($pos.Count -ge 2) { $dests += $pos[1] }
            elseif ($pos.Count -eq 1) {
                $name = ($pos[0] -replace '/$', '') -split '[/\\]' |
                    Select-Object -Last 1
                if ($name.ToLower().EndsWith('.git')) {
                    $name = $name.Substring(0, $name.Length - 4)
                }
                # pure string join: Join-Path would probe the drive,
                # and policy must judge paths that do not exist yet
                $dests += ($base.TrimEnd('\', '/') + '\' + $name)
            }
        }
        'init' {
            $pos = @($rest | Where-Object { $_ -notmatch '^-' })
            if ($pos.Count -ge 1) { $dests += $pos[0] }
            else { $dests += $base }
        }
        'worktree' {
            $ai = [array]::IndexOf(
                ($rest | ForEach-Object { $_.ToLower() }), 'add')
            if ($ai -ge 0 -and $ai + 1 -lt $rest.Count) {
                $dests += $rest[$ai + 1]
            }
        }
        'submodule' {
            $ai = [array]::IndexOf(
                ($rest | ForEach-Object { $_.ToLower() }), 'add')
            if ($ai -ge 0) {
                $pos = @($rest[($ai + 1)..($rest.Count - 1)] |
                    Where-Object { $_ -notmatch '^-' })
                if ($pos.Count -ge 2) { $dests += $pos[1] }
            }
        }
    }
    return $dests
}

function global:git {
    if (-not $script:RepoHomeRealGit) {
        $script:RepoHomeRealGit = Get-Command git `
            -CommandType Application | Select-Object -First 1
    }
    $bad = @()
    foreach ($d in (_RepoHome-Destinations $args)) {
        try { $full = $ExecutionContext.SessionState.Path.`
            GetUnresolvedProviderPathFromPSPath($d) }
        catch { continue }
        if (-not (Test-RepoHomePath $full)) { $bad += $full }
    }
    if ($bad.Count -gt 0) {
        Write-Host "[repo-home-guard] REFUSED (repo home is D:\):" `
            -NoNewline
        Write-Host (" " + ($bad -join ', '))
        Write-Host (Get-RepoHomePolicy)
        # scripts check $LASTEXITCODE after git; a function return
        # value alone would leave them reading the previous command's
        $global:LASTEXITCODE = 128
        return 1
    }
    & $script:RepoHomeRealGit.Source @args
}
