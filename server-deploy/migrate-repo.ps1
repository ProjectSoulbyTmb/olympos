# Adds the Hetzner Forgejo remote and mirror-pushes this repository.
# Usage: .\server-deploy\migrate-repo.ps1 -Owner <forgejo-owner> -Repo olympos
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$Owner,
    [Parameter(Mandatory)] [string]$Repo,
    [string]$RemoteName = 'hetzner',
    [int]$GitPort = 2222
)

$ErrorActionPreference = 'Stop'
$url = "ssh://git@git.eidovara.org:$GitPort/$Owner/$Repo.git"

if (-not (git remote | Where-Object { $_ -eq $RemoteName })) {
    git remote add $RemoteName $url
    Write-Host "remote '$RemoteName' added -> $url"
} else {
    git remote set-url $RemoteName $url
    Write-Host "remote '$RemoteName' updated -> $url"
}

Write-Host "mirror-pushing all refs and tags (LFS objects included)..."
git push --mirror $RemoteName

Write-Host ""
Write-Host "verify with a clean clone:"
Write-Host "  git clone $url C:\Temp\$Repo-test"
