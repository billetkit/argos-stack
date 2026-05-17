#!/bin/bash
# macmini-bootstrap.sh — Run on argos-host (the Mac mini) after the very
# first SSH connection completes. Brings the machine to "Argos can run here"
# state in one command.
#
# Run from the laptop:
#   scp scripts/macmini-bootstrap.sh argos-host:~/
#   ssh argos-host "bash ~/macmini-bootstrap.sh"
#
# Or in person, from the mini:
#   bash macmini-bootstrap.sh
#
# Idempotent — safe to re-run.

set -uo pipefail
log() { echo "[macmini-bootstrap $(date +%H:%M:%S)] $*"; }

# 1. Power/sleep settings — 24/7 host
log "Configuring power: no sleep, auto-restart"
sudo pmset -a sleep 0 disablesleep 1 hibernatemode 0 autorestart 1 2>&1 | tail -2

# 2. Hostname
log "Setting hostname"
sudo scutil --set ComputerName "argos-host" 2>/dev/null
sudo scutil --set LocalHostName "argos-host" 2>/dev/null
sudo scutil --set HostName "argos-host" 2>/dev/null

# 3. Homebrew if missing
if ! command -v brew >/dev/null; then
  log "Installing Homebrew"
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi
eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || true

# 4. Core toolchain
log "Installing core packages"
brew install --quiet python@3.13 node@22 git gh weasyprint pandoc jq tailscale 2>&1 | tail -5

# 5. Ollama
if ! command -v ollama >/dev/null; then
  brew install --cask ollama 2>&1 | tail -2
fi
brew services start ollama 2>&1 | tail -2

# 6. Pull the right model for 64GB Mac mini
# v2: only qwen2.5-coder:32b. No 70B — saves 42GB and ~20 min of bootstrap.
# Path A doesn't need heavyweight reasoning; it needs reliable tool-use.
log "Pulling qwen2.5-coder:32b (~20GB) — production-tier tool-use"
ollama pull qwen2.5-coder:32b 2>&1 | tail -3

# 7. Pre-create the fast variant with 16K context (larger than laptop's 8K since we have RAM)
cat > /tmp/qwen-fast.Modelfile <<'EOF'
FROM qwen2.5-coder:32b
PARAMETER num_ctx 16384
PARAMETER num_predict 8192
EOF
ollama create qwen2.5-coder:32b-fast -f /tmp/qwen-fast.Modelfile 2>&1 | tail -2

# 8. Python deps (pip install requires --break-system-packages on macOS 14+)
log "Installing python deps"
pip3 install --break-system-packages atproto requests pypdf 2>&1 | tail -3

# 9. OpenClaw
if ! command -v openclaw >/dev/null; then
  log "Installing openclaw"
  npm install -g openclaw 2>&1 | tail -3
fi

# 10. Caffeinate-as-launchd for true 24/7
log "Installing caffeinate launchd"
sudo tee /Library/LaunchDaemons/com.argos.caffeinate.plist >/dev/null <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.argos.caffeinate</string>
  <key>ProgramArguments</key><array><string>/usr/bin/caffeinate</string><string>-dimsu</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
EOF
sudo launchctl bootstrap system /Library/LaunchDaemons/com.argos.caffeinate.plist 2>&1 | tail -2
sudo launchctl enable system/com.argos.caffeinate 2>&1 | tail -2

# 11. Remote Login already on per Setup Assistant choice; confirm
sudo systemsetup -setremotelogin on 2>&1 | tail -2

# 12. Done; print state
log "Bootstrap complete."
echo ""
echo "OLLAMA MODELS:"
ollama list | head -10
echo ""
echo "BREW STATUS:"
brew --version | head -1
echo ""
echo "POWER STATE:"
pmset -g | head -10
echo ""
echo "READY FOR v2 migration. Run from the laptop:"
echo "  bash ~/argos/v2/scripts/macmini-migrate-from-laptop.sh"
