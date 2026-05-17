#!/bin/bash
# macmini-migrate-from-laptop.sh — v2 clean migration.
# Run on the laptop AFTER:
#   1) Mac mini Setup Assistant complete
#   2) `argos-host` SSH alias resolves in ~/.ssh/config
#   3) macmini-bootstrap.sh has run on the mini (Homebrew, Ollama, qwen2.5-coder:32b)
#
# This is the v2 path. It only syncs ~/argos/v2/ → mini:~/argos/.
# The mini starts truly clean — no v1 cruft, no 44 PRDs, no PARA tree.
#
# Usage: bash ~/argos/v2/scripts/macmini-migrate-from-laptop.sh

set -uo pipefail
log() { echo "[migrate $(date +%H:%M:%S)] $*"; }

HOST="${ARGOS_HOST:-argos-host}"

log "Verify SSH to $HOST works"
ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "$HOST" "echo OK" || {
  echo "✗ SSH to $HOST failed. Add to ~/.ssh/config:"
  echo ""
  echo "  Host argos-host"
  echo "    HostName <mac-mini-ip>"
  echo "    User argos"
  echo "    ServerAliveInterval 60"
  echo ""
  echo "Then: ssh-copy-id argos-host"
  exit 1
}

log "Rsync v2/ → mini:~/argos/ (clean tree, no v1 cruft)"
rsync -avzP --exclude='__pycache__' --exclude='node_modules' \
  ~/argos/v2/ "$HOST:~/argos/" | tail -8

log "Rsync ~/.openclaw config + secrets"
rsync -avzP ~/.openclaw/ "$HOST:~/.openclaw/" | tail -5

log "Fix permissions on remote secrets"
ssh "$HOST" "chmod 600 ~/.openclaw/secrets.env 2>/dev/null || true"

log "Install python deps on mini if not present"
ssh "$HOST" "pip3 install --break-system-packages --quiet atproto requests pypdf 2>&1 | tail -3"

log "Smoke test: confirm openclaw can hit Ollama on the mini"
ssh "$HOST" "ollama list | head -5"

log "Migration complete. Mac mini has v2 tree at ~/argos/."
echo ""
echo "Next steps (on the mini):"
echo "  ssh $HOST"
echo "  cat ~/argos/PLAN.md          # the Path A blueprint"
echo "  ls ~/argos/scripts/          # 7 working scripts, nothing else"
echo "  ls ~/argos/skills/           # 3 skills ready to package for ClawMart"
