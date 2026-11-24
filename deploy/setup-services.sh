#!/usr/bin/env bash
# Write user systemd units for this checkout. Paths come from the repo
# location and $HOME, so the units are not committed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/.venv/bin/totf-analyzer"
RECORDINGS="$ROOT/Recordings"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
UNIT_DIR="$CONFIG_DIR/systemd/user"
SYNC_ENV="$CONFIG_DIR/totf-analyzer/sync.env"
GAME="$HOME/.local/share/Steam/steamapps/compatdata/3279600/pfx/drive_c/users/steamuser/AppData/LocalLow/Halfbrick Studios/The Thrill of the Fight 2/SessionRecordings"

if [[ ! -x "$BIN" ]]; then
  echo "totf-analyzer is not installed at $BIN" >&2
  echo "Create the venv and run: pip install -e \".[dev]\"" >&2
  exit 1
fi

mkdir -p "$UNIT_DIR" "$RECORDINGS" "$(dirname "$SYNC_ENV")"

cat >"$UNIT_DIR/totf-analyzer-web.service" <<EOF
[Unit]
Description=TotF Analyzer web dashboard (port 8000)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT
Environment="TOTF_RECORDINGS=$RECORDINGS"
Environment="TOTF_GAME_RECORDINGS=$GAME"
EnvironmentFile=-$SYNC_ENV
ExecStart="$BIN" serve --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=10
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=default.target
EOF

cat >"$UNIT_DIR/totf-analyzer-mcp.service" <<EOF
[Unit]
Description=TotF Analyzer MCP (Streamable HTTP on port 8010)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT
Environment="TOTF_RECORDINGS=$RECORDINGS"
Environment="TOTF_GAME_RECORDINGS=$GAME"
EnvironmentFile=-$SYNC_ENV
ExecStart="$BIN" mcp --host 127.0.0.1 --port 8010
Restart=on-failure
RestartSec=10
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=default.target
EOF

cat >"$UNIT_DIR/totf-analyzer-sync.service" <<EOF
[Unit]
Description=Sync Thrill of the Fight 2 recordings from Quest 3 over Wi-Fi
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$ROOT
Environment="TOTF_RECORDINGS=$RECORDINGS"
Environment="TOTF_GAME_RECORDINGS=$GAME"
EnvironmentFile=-$SYNC_ENV
ExecStart="$BIN" sync --quiet
TimeoutStartSec=300
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=6
EOF

cat >"$UNIT_DIR/totf-analyzer-sync.timer" <<EOF
[Unit]
Description=Poll Quest 3 over Wi-Fi every 60s for new Thrill of the Fight 2 recordings

[Timer]
OnBootSec=30s
OnUnitActiveSec=60s
AccuracySec=5s
Unit=totf-analyzer-sync.service

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload

echo "Wrote $UNIT_DIR/totf-analyzer-web.service"
echo "Wrote $UNIT_DIR/totf-analyzer-mcp.service"
echo "Wrote $UNIT_DIR/totf-analyzer-sync.service"
echo "Wrote $UNIT_DIR/totf-analyzer-sync.timer"
if [[ ! -f "$SYNC_ENV" ]]; then
  echo "Optional Quest 3 Wi-Fi sync settings can be placed in: $SYNC_ENV"
fi
echo "Enable them with:"
echo "  systemctl --user enable --now totf-analyzer-web.service"
echo "  systemctl --user enable --now totf-analyzer-mcp.service"
echo "  systemctl --user enable --now totf-analyzer-sync.timer"
echo "If they are already running, restart them to load the new units."
