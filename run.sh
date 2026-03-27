#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Parse flags ───────────────────────────────────────────────────────────────
DEBUG=0
VERBOSE=1
_prev=""
for arg in "$@"; do
  [ "$arg" = "--debug" ] && DEBUG=1
  [ "$_prev" = "--verbose" ] && [ "$arg" = "off" ] && VERBOSE=0
  _prev="$arg"
done

VENV="$SCRIPT_DIR/.venv"
TOWNS_FILE="$SCRIPT_DIR/towns.json"

# ── Ensure venv + requirements ────────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"
echo "Checking requirements..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# ── Read towns ────────────────────────────────────────────────────────────────
if [ ! -f "$TOWNS_FILE" ]; then
    echo "No towns.json found. Run ./addtown.sh <town> <port> <password> first."
    exit 1
fi

TOWNS=$(python3 - <<'PYEOF'
import json, sys
from pathlib import Path
towns = json.loads(Path("towns.json").read_text())
for t in towns:
    h = t.get("password_hash", "")
    if not h:
        print(f"ERROR: town '{t['town']}' has no password_hash. Run: ./changepassword.sh {t['town']} <password>", file=sys.stderr)
        sys.exit(1)
    print(f"{t['town']}|{t['port']}|{h}")
PYEOF
)

if [ -z "$TOWNS" ]; then
    echo "towns.json is empty. Run ./addtown.sh <town> <port> <password> first."
    exit 1
fi

# ── Start each town ───────────────────────────────────────────────────────────
while IFS='|' read -r TOWN PORT HASH; do
    PIDFILE="$SCRIPT_DIR/.${TOWN}.pid"

    # Kill previous instance for this town
    if [ -f "$PIDFILE" ]; then
        OLD_PID=$(cat "$PIDFILE")
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo "[$TOWN] Stopping previous instance (PID $OLD_PID)..."
            kill "$OLD_PID"
            sleep 1
        fi
        rm -f "$PIDFILE"
    fi

    # Kill any stray process on this port
    STRAY=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
    if [ -n "$STRAY" ]; then
        echo "[$TOWN] Killing stray process on port $PORT (PID $STRAY)..."
        kill "$STRAY" 2>/dev/null || true
        sleep 1
    fi

    # Migrate database before starting
    echo "[$TOWN] Running migrations..."
    TOWN="$TOWN" ADMIN_PASSWORD_HASH="$HASH" flask db upgrade

    # Start
    if [ "$DEBUG" = "1" ]; then
        echo "[$TOWN] Starting on port $PORT (Werkzeug debug)..."
        #in debug mode, run single town at a time. keep console attached.
        TOWN="$TOWN" PORT="$PORT" ADMIN_PASSWORD_HASH="$HASH" VERBOSE="$VERBOSE" python wsgi.py
    else
        echo "[$TOWN] Starting on port $PORT (gunicorn)..."
        TOWN="$TOWN" PORT="$PORT" ADMIN_PASSWORD_HASH="$HASH" FLASK_DEBUG=0 VERBOSE="$VERBOSE" \
            gunicorn --bind "0.0.0.0:$PORT" --workers 1 --timeout 120 wsgi:app &
    fi
    echo $! > "$PIDFILE"
    echo "[$TOWN] Running as PID $(cat $PIDFILE)"

done <<< "$TOWNS"

echo ""
echo "All towns started. Stop with: kill \$(cat .<town>.pid)"
