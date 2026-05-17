#!/bin/bash
# argos-backup.sh — Nightly local snapshot of critical state.
#
# This is poor-man's backup to a local folder (same disk). Not real disaster
# recovery — that needs external storage. But it protects against accidental
# `rm -rf`, bad edit, corrupted file, runaway script wiping memory dirs.
#
# Fires nightly at 02:30 via LaunchAgent.

set -uo pipefail

TIMESTAMP=$(date -u +%Y-%m-%dT%H-%M-%S)
BACKUP_ROOT=~/Backups/argos
BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"

mkdir -p "$BACKUP_DIR"
echo "[backup] writing to $BACKUP_DIR" >&2

# 1. Argos workspace (excluding noisy logs + cached models)
rsync -a \
  --exclude='memory/heartbeat*.log' \
  --exclude='memory/telegram-bot*.log' \
  --exclude='memory/dashboard-*.log' \
  --exclude='memory/img-server*.log' \
  --exclude='memory/litellm*.log' \
  --exclude='memory/operator-inbox/archive' \
  --exclude='__pycache__' \
  ~/argos/ "$BACKUP_DIR/argos/" 2>&1 | tail -5

# 2. OpenClaw config + secrets (these are the keys to everything)
rsync -a ~/.openclaw/openclaw.json "$BACKUP_DIR/openclaw.json" 2>&1 | tail -2
cp ~/.openclaw/secrets.env "$BACKUP_DIR/secrets.env" 2>/dev/null
chmod 600 "$BACKUP_DIR/secrets.env"

# 3. LaunchAgent plists (so we can re-register services after a restore)
mkdir -p "$BACKUP_DIR/LaunchAgents"
cp ~/Library/LaunchAgents/com.argos.*.plist "$BACKUP_DIR/LaunchAgents/" 2>/dev/null

# 4. Langfuse postgres dump (the trace history — irreplaceable signal)
docker exec langfuse-postgres-1 pg_dump -U postgres langfuse 2>/dev/null | gzip > "$BACKUP_DIR/langfuse.sql.gz"

# 5. Quick summary file
cat > "$BACKUP_DIR/MANIFEST.md" <<EOF
# Backup · $TIMESTAMP

- argos workspace: ~$(du -sh "$BACKUP_DIR/argos" 2>/dev/null | awk '{print $1}')
- openclaw.json: $(stat -f%z "$BACKUP_DIR/openclaw.json" 2>/dev/null) bytes
- secrets.env: $(stat -f%z "$BACKUP_DIR/secrets.env" 2>/dev/null) bytes
- LaunchAgents: $(ls "$BACKUP_DIR/LaunchAgents/" 2>/dev/null | wc -l) plists
- langfuse postgres dump: $(stat -f%z "$BACKUP_DIR/langfuse.sql.gz" 2>/dev/null) bytes (gzipped)

To restore:
  rsync -av "$BACKUP_DIR/argos/" ~/argos/
  cp "$BACKUP_DIR/openclaw.json" ~/.openclaw/
  cp "$BACKUP_DIR/secrets.env" ~/.openclaw/
  cp "$BACKUP_DIR/LaunchAgents/"*.plist ~/Library/LaunchAgents/
  gunzip -c "$BACKUP_DIR/langfuse.sql.gz" | docker exec -i langfuse-postgres-1 psql -U postgres langfuse
EOF

# 6. Retain last 7 backups, delete older
cd "$BACKUP_ROOT" || exit 1
ls -t | tail -n +8 | xargs -I {} rm -rf {} 2>/dev/null

echo "[backup] $TIMESTAMP done. Kept latest 7." >&2
