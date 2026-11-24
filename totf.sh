#!/usr/bin/env bash
# Choose a foreground run, Quest 3 sync, systemd user-service install, or uninstall.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$ROOT/.venv/bin/totf-analyzer"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNITS=(
  totf-analyzer-web.service
  totf-analyzer-mcp.service
  totf-analyzer-sync.timer
  totf-analyzer-sync.service
)
LEGACY_UNITS=(totf2-sync.timer totf2-sync.service)
cd "$ROOT"

require_app() {
  if [[ ! -x "$BIN" ]]; then
    echo "totf-analyzer is not installed at $BIN" >&2
    echo "Create the venv and run: pip install -e \".[dev]\"" >&2
    return 1
  fi
}

services_active() {
  systemctl --user is-active --quiet totf-analyzer-web.service && return 0
  systemctl --user is-active --quiet totf-analyzer-mcp.service
}

run_foreground() {
  require_app || return 1
  if services_active; then
    echo "The systemd services are already running."
    echo "Dashboard  http://127.0.0.1:8000"
    echo "MCP        http://127.0.0.1:8010/mcp"
    echo "Stop them before a foreground run:"
    echo "  systemctl --user stop totf-analyzer-web.service totf-analyzer-mcp.service"
    return 1
  fi
  if [[ ! -f "$ROOT/web/dist/index.html" ]]; then
    echo "The dashboard UI is not built. The API will still run."
    echo "Build it with: cd web && npm install && npm run build"
  fi

  export TOTF_RECORDINGS="${TOTF_RECORDINGS:-$ROOT/Recordings}"
  mkdir -p "$TOTF_RECORDINGS"

  local web_pid="" mcp_pid=""
  cleanup() {
    trap - RETURN INT TERM
    if [[ -n "$web_pid" ]]; then
      kill "$web_pid" 2>/dev/null || true
    fi
    if [[ -n "$mcp_pid" ]]; then
      kill "$mcp_pid" 2>/dev/null || true
    fi
    wait "$web_pid" "$mcp_pid" 2>/dev/null || true
    web_pid=""
    mcp_pid=""
  }

  echo "Web dashboard  http://127.0.0.1:8000"
  echo "MCP            http://127.0.0.1:8010/mcp"
  echo "Press Ctrl+C to stop."

  "$BIN" serve --host 127.0.0.1 --port 8000 &
  web_pid=$!
  "$BIN" mcp --host 127.0.0.1 --port 8010 &
  mcp_pid=$!
  trap cleanup RETURN INT TERM
  set +e
  wait -n "$web_pid" "$mcp_pid"
  set -e
  cleanup
}

run_quest_sync() {
  require_app || return 1
  export TOTF_RECORDINGS="${TOTF_RECORDINGS:-$ROOT/Recordings}"
  mkdir -p "$TOTF_RECORDINGS"
  "$BIN" sync --status || true
  echo ""
  "$BIN" sync || true
}

migrate_legacy_sync_units() {
  local unit found=0
  for unit in "${LEGACY_UNITS[@]}"; do
    if [[ -f "$UNIT_DIR/$unit" ]] || systemctl --user is-enabled --quiet "$unit" 2>/dev/null; then
      found=1
      systemctl --user disable --now "$unit" 2>/dev/null || true
      rm -f "$UNIT_DIR/$unit" "$UNIT_DIR/timers.target.wants/$unit" "$UNIT_DIR/default.target.wants/$unit"
    fi
  done
  if [[ "$found" -eq 1 ]]; then
    systemctl --user daemon-reload
    systemctl --user reset-failed "${LEGACY_UNITS[@]}" 2>/dev/null || true
    echo "Migrated legacy totf2-sync user units to totf-analyzer-sync.timer."
  fi
}

install_service() {
  require_app || return 1
  migrate_legacy_sync_units
  "$ROOT/deploy/setup-services.sh"
  systemctl --user enable --now totf-analyzer-web.service totf-analyzer-mcp.service totf-analyzer-sync.timer
  systemctl --user restart totf-analyzer-web.service totf-analyzer-mcp.service
  echo "Installed and started the user services."
  echo "Dashboard  http://127.0.0.1:8000"
  echo "MCP        http://127.0.0.1:8010/mcp"
  echo "Quest Sync totf-analyzer-sync.timer (polls every 60s)"
  if ! loginctl show-user "$USER" -p Linger --value 2>/dev/null | grep -qx yes; then
    echo "These services stop at logout. To start them at boot:"
    echo "  sudo loginctl enable-linger $USER"
  fi
}

uninstall_service() {
  local unit
  for unit in "${UNITS[@]}"; do
    systemctl --user disable --now "$unit" 2>/dev/null || true
    rm -f "$UNIT_DIR/$unit" "$UNIT_DIR/default.target.wants/$unit" "$UNIT_DIR/timers.target.wants/$unit"
  done
  systemctl --user daemon-reload
  systemctl --user reset-failed "${UNITS[@]}" 2>/dev/null || true
  echo "Removed the user services."
}

if [[ $# -ne 0 ]]; then
  echo "Usage: ./totf.sh" >&2
  echo "Run it with no arguments to open the menu." >&2
  exit 2
fi

echo "TotF Analyzer"
PS3="Select: "
options=(
  "Run now, without installing a service"
  "Sync from Quest 3 now (status + pull)"
  "Install as a systemd service (web, MCP, Quest 3 sync timer)"
  "Uninstall the systemd services"
  "Quit"
)
select _choice in "${options[@]}"; do
  case "$REPLY" in
    1) run_foreground || true ;;
    2) run_quest_sync || true ;;
    3) install_service || true ;;
    4) uninstall_service || true ;;
    5) break ;;
    *) echo "Enter 1, 2, 3, 4, or 5." ;;
  esac
done
