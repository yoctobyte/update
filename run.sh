#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

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

TOWNS=$(python3 -c "
import json
towns = json.load(open('$TOWNS_FILE'))
for t in towns:
    print(t['town'], t['port'], t['password'])
")

if [ -z "$TOWNS" ]; then
    echo "towns.json is empty. Run ./addtown.sh <town> <port> <password> first."
    exit 1
fi

# ── Start each town ───────────────────────────────────────────────────────────
while IFS=' ' read -r TOWN PORT PASSWORD; do
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
    TOWN="$TOWN" flask db upgrade

    # Start
    echo "[$TOWN] Starting on port $PORT..."
    TOWN="$TOWN" PORT="$PORT" ADMIN_PASSWORD="$PASSWORD" FLASK_DEBUG="${FLASK_DEBUG:-0}" python wsgi.py &
    echo $! > "$PIDFILE"
    echo "[$TOWN] Running as PID $(cat $PIDFILE)"

done <<< "$TOWNS"

echo ""
echo "All towns started. Stop with: kill \$(cat .<town>.pid)"
