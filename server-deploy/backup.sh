#!/usr/bin/env bash
# Nightly encrypted snapshot of Forgejo data -> Hetzner Object Storage.
# No-op until S3_* values exist in .env. Cron-installed by bootstrap.sh.
set -euo pipefail

DEPLOY_DIR="/opt/eidovara"
cd "$DEPLOY_DIR"

set -a; source "$DEPLOY_DIR/.env"; set +a

if [[ -z "${S3_ENDPOINT:-}" || -z "${S3_ACCESS_KEY_ID:-}" ]]; then
  echo "$(date -Is) backup skipped: object storage not configured yet"
  exit 0
fi

export RESTIC_REPOSITORY="s3:${S3_ENDPOINT}/${S3_BUCKET_BACKUPS}"
export RESTIC_PASSWORD="${RESTIC_PASSWORD:?RESTIC_PASSWORD missing in .env}"
export AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$S3_SECRET_ACCESS_KEY"

echo "$(date -Is) backup start"
docker compose stop forgejo
restic backup data
docker compose start forgejo

restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
restic check --read-data-subset=5%
echo "$(date -Is) backup done"
