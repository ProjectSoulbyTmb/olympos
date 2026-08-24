# flow.ps1 - multi-agent git flow helper for the Soul Platform fleet.
#
# Each automator owns one git worktree under .worktrees\<name> and one
# branch auto\<name>. Shipping = commit in your worktree, push your
# branch, open a PR against main, (optionally) merge it squash-style,
# then fast-forward the integration mirror.
#
#   powershell -File flow.ps1 list
#   powershell -File flow.ps1 start -Name hermes
#   powershell -File flow.ps1 sync  -Name hermes
#   powershell -File flow.ps1 ship  -Name hermes -Message "fix: thing"
#   powershell -File flow.ps1 ship  -Name hermes -Message "wip" -NoMerge
#   powershell -File flow.ps1 install-hooks

param(
    [Parameter(Mandatory = $true)][string]$Cmd,
    [string]$Name,
    [string]$Message,
    [switch]$NoMerge
)

$ErrorActionPreference = "Continue"   # native tools report via exit codes
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$wtRoot = Join-Path $root ".worktrees"

function WorktreePath([string]$n) { Join-Path $wtRoot $n }

function Die([string]$msg) {
    Write-Host "ERROR: $msg"
    exit 1
}

function Start-Flow([string]$n) {
    $branch = "auto/$n"
    $path = WorktreePath $n
    if (Test-Path $path) {
        Write-Host "worktree exists: $path (branch $branch)"
        return
    }
    & git -C $root worktree add $path -b $branch --quiet
    if ($LASTEXITCODE -ne 0) { Die "could not create worktree $path" }
    Write-Host "created worktree $path on branch $branch"
}

function Sync-Flow([string]$n) {
    $path = WorktreePath $n
    if (-not (Test-Path $path)) { Die "no such worktree: $path" }
    & git -C $path fetch origin --prune --quiet
    # integration mirror fast-forwards; branches absorb main by merge
    & git -C $path pull --ff-only origin main --quiet 2>$null
    if ($LASTEXITCODE -ne 0) {
        & git -C $path merge origin/main --no-edit --quiet 2>$null
        if ($LASTEXITCODE -ne 0) { Die "merge conflicts in $n - resolve, commit, re-run ship" }
    }
    Write-Host "$n synced with origin/main"
}

function Ship-Flow([string]$n, [string]$msg, [bool]$noMerge) {
    if (-not $msg) { Die "ship requires -Message" }
    $path = WorktreePath $n
    if (-not (Test-Path $path)) { Die "no such worktree: $path (run start first)" }
    $branch = "auto/$n"

    & git -C $path add -A
    $staged = & git -C $path status --short
    if ($staged) {
        & git -C $path commit -m $msg --quiet
        if ($LASTEXITCODE -ne 0) { Die "commit failed" }
    } else {
        # nothing new to commit: fine if the branch is simply ahead
        & git -C $path fetch origin --quiet
        $ahead = (& git -C $path rev-list --count "origin/main..$branch")
        if ([string]::IsNullOrWhiteSpace("$ahead") -or [int]($ahead) -le 0) {
            Die "nothing to ship in $path"
        }
    }

    & git -C $path push -u origin $branch --quiet
    if ($LASTEXITCODE -ne 0) { Die "push failed for $branch" }

    $existing = ""
    $existing = (& gh pr list --head $branch --state open --json number -q ".[0].number" 2>$null)
    if ([string]::IsNullOrEmpty("$existing")) {
        $out = (& gh pr create --base main --head $branch --title $msg --body "Automated shipment from worktree '$n'. Verified per FLOW.md protocol." 2>$null)
        if ($LASTEXITCODE -ne 0) { Die "gh pr create failed: $out" }
        Write-Host "opened PR: $out"
        $pr = "$out".Trim()
    } else {
        $pr = "$existing".Trim()
        Write-Host "PR #$pr updated"
    }

    if ($noMerge) {
        Write-Host "left open for human review: $pr"
        return
    }
    & gh pr merge $pr --squash --delete-branch 2>$null
    if ($LASTEXITCODE -ne 0) { Die "PR merge failed for $pr" }
    Write-Host "merged: $pr"

    # refresh the integration mirror so the root checkout follows main
    & git -C $root pull --ff-only origin main --quiet 2>$null
    Write-Host "mirror fast-forwarded"
}

function Install-Hooks {
    # Copy the canonical tracked hook into the clone's COMMON hook dir
    # (main .git) so every worktree refuses direct pushes to main.
    $src = Join-Path $root "hooks\pre-push"
    if (-not (Test-Path $src)) { Die "canonical hook missing: hooks/pre-push" }
    $common = (& git -C $root rev-parse --path-format=absolute --git-common-dir)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace("$common")) {
        Die "could not resolve git common dir"
    }
    $hookDir = Join-Path "$common" "hooks"
    New-Item -ItemType Directory -Force -Path $hookDir | Out-Null
    $dst = Join-Path $hookDir "pre-push"
    Copy-Item $src $dst -Force
    if (-not (Test-Path $dst)) { Die "hook install failed: $dst" }
    Write-Host "pre-push guard installed -> $dst"
}

switch ($Cmd) {
    "list" {
        & git -C $root worktree list
    }
    "install-hooks" {
        Install-Hooks
    }
    "start" {
        if (-not $Name) { Die "start requires -Name" }
        Start-Flow $Name
    }
    "sync" {
        if (-not $Name) { Die "sync requires -Name" }
        Sync-Flow $Name
    }
    "ship" {
        Ship-Flow $Name $Message ([bool]$NoMerge)
    }
    default {
        Die "unknown command: $Cmd (use list|start|sync|ship|install-hooks)"
    }
}
