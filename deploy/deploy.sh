#!/usr/bin/env bash
# deploy.sh — Pull latest code and restart the service if anything changed.
#
# Usage (manual):
#   ./deploy.sh
#
# Automated via cron (every 5 minutes):
#   */5 * * * * /opt/entfernungsspiel/deploy/deploy.sh >> /var/log/entfernungsspiel-deploy.log 2>&1
#
# Automated via git post-receive hook on the server:
#   Copy or symlink this script as .git/hooks/post-receive
#
set -euo pipefail

SERVICE="entfernungsspiel"
# Resolve the project root relative to this script's location
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$APP_DIR/.venv"

cd "$APP_DIR"

# ------------------------------------------------------------------
# 1. Record the current commit before pulling
# ------------------------------------------------------------------
BEFORE=$(git rev-parse HEAD)

# ------------------------------------------------------------------
# 2. Pull latest changes
# ------------------------------------------------------------------
echo "[deploy] git pull..."
git pull --ff-only

AFTER=$(git rev-parse HEAD)

# ------------------------------------------------------------------
# 3. Nothing changed — skip restart
# ------------------------------------------------------------------
if [ "$BEFORE" = "$AFTER" ]; then
    echo "[deploy] Already up to date. No restart needed."
    exit 0
fi

echo "[deploy] $BEFORE -> $AFTER"

# ------------------------------------------------------------------
# 4. Update Python dependencies if requirements.txt changed
# ------------------------------------------------------------------
if git diff --name-only "$BEFORE" "$AFTER" | grep -q "requirements.txt"; then
    echo "[deploy] requirements.txt changed — updating dependencies..."
    "$VENV/bin/pip" install --quiet -r requirements.txt
fi

# ------------------------------------------------------------------
# 5. Restart the systemd service
# ------------------------------------------------------------------
echo "[deploy] Restarting $SERVICE..."
sudo systemctl restart "$SERVICE"
echo "[deploy] Done."
