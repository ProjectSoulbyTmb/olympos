# eidovara.org git server deployment kit

Self-hosted private git hosting (Forgejo) at `https://git.eidovara.org`
on a Hetzner CX22, with S3-compatible Hetzner Object Storage for backups
and dataset archives. Large media is versioned in-repo via Git LFS.

## Architecture

```
Windows workstation (this machine)
  │  ssh admin (port 22)          ssh git (port 2222)
  ▼                                ▼
Hetzner CX22 (Ubuntu 24.04) ── Caddy :443 ── Forgejo :3000 (Docker)
  │                                  + Git LFS inside repos
  ▼ nightly restic (encrypted)
Hetzner Object Storage bucket  (backups)
Hetzner Object Storage bucket  (datasets/archives via rclone)
```

## Cost

| Item | Price |
|---|---|
| CX22 (2 vCPU / 4 GB / 40 GB) | ~$5/mo |
| Object Storage (1 TB + 1 TB egress incl.) | ~$8/mo |
| **Total** | **~$13/mo** |

## Files

| File | Purpose |
|---|---|
| `provision-hetzner.ps1` | Creates the server via Hetzner API (uploads deploy key, waits for IP) |
| `bootstrap.sh` | Run on server: hardening, Docker, stack up, backup cron |
| `docker-compose.yml` | Forgejo + Caddy stack definition |
| `Caddyfile` | HTTPS reverse proxy, auto Let's Encrypt certs |
| `backup.sh` | Nightly encrypted restic snapshot -> object storage |
| `migrate-repo.ps1` | Adds `hetzner` remote and mirror-pushes this repo |
| `.env.example` | Secret template (real `.env` lives only on server) |

## Manual steps (account owner only)

1. Create account at <https://console.hetzner.cloud>, make a project,
   generate an **API token** (read/write).
2. In Cloudflare DNS for `eidovara.org`: add `git` A record after the IP
   is known — set to **DNS only** (grey cloud; avoids Cloudflare's
   100 MB upload limit on LFS pushes).
3. Create an Object Storage bucket in the same location as the server
   (free internal transfer), plus S3 credentials.

## Automated steps

Everything else is scripted:

```powershell
# from repo root, with your token:
.\server-deploy\provision-hetzner.ps1 -Token <TOKEN> -Location ash
# prints SERVER_IP -> add Cloudflare 'git' A record now if not done

scp -r server-deploy root@SERVER_IP:/opt/eidovara
ssh root@SERVER_IP "ACME_EMAIL=<you@example.com> bash /opt/eidovara/bootstrap.sh"

# back on Windows:
.\server-deploy\migrate-repo.ps1 -Owner <forgejo-owner> -Repo olympos
```

Then create your Forgejo admin user on first visit to
<https://git.eidovara.org> (registration is disabled by design).

## Security notes

- Root SSH: key-only (`PermitRootLogin prohibit-password`), password auth off
- ufw allows 22/80/443/2222 only; fail2ban active; unattended-upgrades on
- Secrets live in `/opt/eidovara/.env` (mode 600), never committed here
- Backups encrypted client-side by restic before leaving the server
