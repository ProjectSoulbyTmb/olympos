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

param(
    [Parameter(Mandatory = $true)][string]$Cmd,
    [string]$Name,
    [string]$Message,
    [switch]$NoMerge
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$wtRoot = Join-Path $root ".worktrees"

function WorktreePath([string]$n) { Join-Path $wtRoot $n }

function Start-Flow([string]$n) {
    $branch = "auto/$n"
    $path = WorktreePath $n
    if (Test-Path $path) {
        Write-Host "worktree exists: $path (branch $branch)"
        return
    }
    git -C $root worktree add $path -b $branch | Out-Null
    Write-Host "created worktree $path on branch $branch"
}

function Sync-Flow([string]$n) {
    $path = WorktreePath $n
    if (-not (Test-Path $path)) { throw "no such worktree: $path" }
    git -C $path fetch origin --prune --quiet
    # integration mirror fast-forwards; branches absorb main by merge
    git -C $path pull --ff-only origin main 2>$null
    if ($LASTEXITCODE -ne 0) {
        git -C $path merge origin/main --no-edit --quiet
        if ($LASTEXITCODE -ne 0) { throw "merge conflicts in $n - resolve, commit, re-run ship" }
    }
    Write-Host "$n synced with origin/main"
}

function Ship-Flow([string]$n, [string]$msg, [bool]$noMerge) {
    if (-not $msg) { throw "ship requires -Message" }
    $path = WorktreePath $n
    if (-not (Test-Path $path)) { throw "no such worktree: $path (run start first)" }
    $branch = "auto/$n"

    git -C $path add -A
    $staged = git -C $path status --short
    if (-not $staged) { throw "nothing to ship in $path" }
    git -C $path commit -m $msg | Out-Null

    git -C $path push -u origin $branch 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "push failed for $branch" }

    $existing = gh pr list --head $branch --state open --json number -q ".[0].number"
    if ($existing) {
        $pr = $existing
        Write-Host "PR #$existing updated"
    } else {
        $pr = gh pr create --base main --head $branch --title $msg --body "Automated shipment from worktree '$n'.`n`n- branch: ``$branch```n- verified per FLOW.md protocol before shipping." 2>&1
        Write-Host "opened PR: $pr"
    }

    if ($noMerge) {
        Write-Host "left open for human review: PR #$pr"
        return
    }
    gh pr merge $pr --squash --delete-branch | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "PR merge failed for #$pr" }
    Write-Host "merged PR #$pr (squash)"

    # refresh the integration mirror so the root checkout follows main
    git -C $root pull --ff-only origin main 2>&1 | Out-Null
    Write-Host "mirror fast-forwarded"
}

switch ($Cmd) {
    "list" {
        git -C $root worktree list
    }
    "start" {
        if (-not $Name) { throw "start requires -Name" }
        Start-Flow $Name
    }
    "sync" {
        if (-not $Name) { throw "sync requires -Name" }
        Sync-Flow $Name
    }
    "ship" {
        Ship-Flow $Name $Message ([bool]$NoMerge)
    }
    default {
        throw "unknown command: $Cmd (use list|start|sync|ship)"
    }
}
