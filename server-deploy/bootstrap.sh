#!/usr/bin/env bash
# eidovara.org git server bootstrap - run ONCE on a fresh Ubuntu 24.04 host.
# Usage: ACME_EMAIL=you@example.com bash /opt/eidovara/bootstrap.sh
set -euo pipefail

DOMAIN="git.eidovara.org"
DEPLOY_DIR="/opt/eidovara"
DEPLOY_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQRed3wddTmtyq8P9qV1wFklaYJSSFkNA0gBW1/UKX4 eidovara-deploy@DESKTOP-O1LPG5B"

: "${ACME_EMAIL:?export ACME_EMAIL before running}"

echo "==> [1/7] packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get -yqq upgrade
apt-get install -yqq ufw fail2ban unattended-upgrades curl ca-certificates openssl rclone restic

echo "==> [2/7] ssh hardening"
install -d -m 700 /root/.ssh
grep -qxF "$DEPLOY_PUBKEY" /root/.ssh/authorized_keys 2>/dev/null \
  || echo "$DEPLOY_PUBKEY" >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
cat > /etc/ssh/sshd_config.d/99-hardening.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
X11Forwarding no
MaxAuthTries 3
EOF
systemctl restart ssh

echo "==> [3/7] firewall"
ufw allow OpenSSH >/dev/null
ufw allow 80,443/tcp >/dev/null
ufw allow 2222/tcp comment 'git ssh' >/dev/null
ufw --force enable >/dev/null
systemctl enable --now fail2ban unattended-upgrades >/dev/null 2>&1 || true

echo "==> [4/7] docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

echo "==> [5/7] secrets"
cd "$DEPLOY_DIR"
if [[ ! -f .env ]]; then
  cat > .env <<EOF
GIT_DOMAIN=${DOMAIN}
ACME_EMAIL=${ACME_EMAIL}
FORGEJO_LFS_JWT_SECRET=$(openssl rand -hex 32)
FORGEJO_SECRET_KEY=$(openssl rand -hex 32)
FORGEJO_OAUTH2_JWT_SECRET=$(openssl rand -hex 32)
S3_ENDPOINT=
S3_BUCKET_BACKUPS=eidovara-backups
S3_BUCKET_DATASETS=eidovara-datasets
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
RESTIC_PASSWORD=$(openssl rand -base64 24)
EOF
  echo "    created $DEPLOY_DIR/.env - fill S3_* values, keep RESTIC_PASSWORD safe offline"
fi
chmod 600 .env

echo "==> [6/7] stack up"
docker compose up -d

echo "==> [7/7] nightly backup cron (activates once S3 creds are filled in)"
install -m 750 backup.sh /usr/local/local-backup.sh 2>/dev/null || true
( crontab -l 2>/dev/null | grep -v eidovara-backup ;
  echo "0 3 * * * $DEPLOY_DIR/backup.sh >> /var/log/eidovara-backup.log 2>&1 # eidovara-backup" ) | crontab -

echo
echo "DONE. Next:"
echo "  1. fill in S3_* in $DEPLOY_DIR/.env   (Object Storage credentials)"
echo "  2. visit https://${DOMAIN} and create the admin user (first registration window)"
echo "     if you missed it: docker compose exec -u 1000 forgejo forgejo admin user create --admin --username <u> --password <p> --email <e>"
