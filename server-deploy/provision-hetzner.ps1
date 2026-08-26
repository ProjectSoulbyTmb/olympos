# Provisions the eidovara git server on Hetzner Cloud via API.
# Usage: .\server-deploy\provision-hetzner.ps1 -Token <API_TOKEN> [-Location ash]
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$Token,
    [ValidateSet('ash','fsn','nbg','hel')] [string]$Location = 'ash',
    [string]$ServerName = 'eidovara-git',
    [string]$ServerType = 'cx22',
    [string]$Image = 'ubuntu-24.04'
)

$ErrorActionPreference = 'Stop'
$pub = Get-Content "$env:USERPROFILE\.ssh\id_ed25519_eidovara.pub" -Raw
$headers = @{ Authorization = "Bearer $Token"; 'Content-Type' = 'application/json' }
$base = 'https://api.hetzner.cloud/v1'

Write-Host "==> uploading deploy key"
$keyName = 'eidovara-deploy'
try {
    Invoke-RestMethod -Method Post -Uri "$base/ssh_keys" -Headers $headers -Body (
        @{ name = $keyName; public_key = $pub.Trim() } | ConvertTo-Json) | Out-Null
} catch {
    # 409/422 unprocessable = already exists, fine
    if ($_.Exception.Response.StatusCode.value__ -notin 409, 422) { throw }
}

Write-Host "==> creating $ServerType in $Location ($Image)"
$body = @{
    name               = $ServerName
    server_type        = $ServerType
    image              = $Image
    location           = $Location
    ssh_keys           = @($keyName)
    start_after_create = $true
} | ConvertTo-Json

$resp = Invoke-RestMethod -Method Post -Uri "$base/servers" -Headers $headers -Body $body
$id = $resp.server.id
$ip = $resp.server.public_net.ipv4.ip
Write-Host "    server id=$id initial ip=$ip"

while ($true) {
    Start-Sleep -Seconds 5
    $s = (Invoke-RestMethod -Method Get -Uri "$base/servers/$id" -Headers $headers).server
    Write-Host "    status: $($s.status)"
    if ($s.status -eq 'running') { break }
}

Write-Host ""
Write-Host "SERVER_IP = $ip"
Write-Host "NEXT:"
Write-Host "  1. Cloudflare DNS: add 'git' A record -> $ip (DNS only / grey cloud)"
Write-Host "  2. scp -r server-deploy root@${ip}:/opt/eidovara"
Write-Host "  3. ssh root@$ip `"ACME_EMAIL=<you@example.com> bash /opt/eidovara/bootstrap.sh`""
