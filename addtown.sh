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

# ── Hash password + update towns.json ────────────────────────────────────────
TOWN_NAME="$TOWN" PORT_NUM="$PORT" TOWN_PASS="$PASSWORD" python3 - <<'PYEOF'
import os, json, sys, bcrypt
from pathlib import Path

town     = os.environ["TOWN_NAME"]
port     = int(os.environ["PORT_NUM"])
password = os.environ["TOWN_PASS"]

pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

towns_file = Path("towns.json")
towns = json.loads(towns_file.read_text()) if towns_file.exists() else []

for t in towns:
    if t["town"] == town:
        print(f"Town '{town}' already exists. Remove it from towns.json first.")
        sys.exit(1)
    if t["port"] == port:
        print(f"Port {port} is already in use by town '{t['town']}'.")
        sys.exit(1)

towns.append({"town": town, "port": port, "password_hash": pw_hash})
towns_file.write_text(json.dumps(towns, indent=2))
print(f"Added town '{town}' on port {port}.")
PYEOF

# ── Init town database ────────────────────────────────────────────────────────
echo "Initializing town '$TOWN'..."
TOWN="$TOWN" flask --app wsgi init-town "$TOWN"

echo ""
echo "Done. Run ./run.sh to start all towns."
