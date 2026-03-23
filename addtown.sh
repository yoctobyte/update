#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

TOWNS_FILE="$SCRIPT_DIR/towns.json"
VENV="$SCRIPT_DIR/.venv"

# ── Args ──────────────────────────────────────────────────────────────────────
if [ $# -ne 3 ]; then
    echo "Usage: $0 <town> <port> <password>"
    echo "Example: $0 haarlem 5001 geheim123"
    exit 1
fi

TOWN="$1"
PORT="$2"
PASSWORD="$3"

# ── Validate ──────────────────────────────────────────────────────────────────
if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
    echo "Error: port must be a number"
    exit 1
fi

# ── Ensure venv + requirements ────────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"
pip install -q --upgrade pip
pip install -q -r requirements.txt

# ── Update towns.json ─────────────────────────────────────────────────────────
python3 - <<EOF
import json, sys
from pathlib import Path

towns_file = Path("$TOWNS_FILE")
towns = json.loads(towns_file.read_text()) if towns_file.exists() else []

# Check for conflicts
for t in towns:
    if t["town"] == "$TOWN":
        print(f"Town '$TOWN' already exists. Remove it from towns.json first.")
        sys.exit(1)
    if t["port"] == $PORT:
        print(f"Port $PORT is already in use by town '{t['town']}'.")
        sys.exit(1)

towns.append({"town": "$TOWN", "port": $PORT, "password": "$PASSWORD"})
towns_file.write_text(json.dumps(towns, indent=2))
print(f"Added town '$TOWN' on port $PORT.")
EOF

# ── Init town database ────────────────────────────────────────────────────────
echo "Initializing town '$TOWN'..."
TOWN="$TOWN" ADMIN_PASSWORD="$PASSWORD" flask --app wsgi init-town "$TOWN"

echo ""
echo "Done. Run ./run.sh to start all towns."
