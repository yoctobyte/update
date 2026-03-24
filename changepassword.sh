#!/usr/bin/env bash
# changepassword.sh — set or update the admin password for a town.
# Also use this to migrate an existing towns.json entry from plaintext to bcrypt.
#
# Usage: ./changepassword.sh <town> <new-password>

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ $# -ne 2 ]; then
    echo "Usage: $0 <town> <new-password>"
    echo "Example: $0 wageningen geheim123"
    exit 1
fi

VENV="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV" ]; then
    echo "No venv found. Run ./run.sh once first to set up the environment."
    exit 1
fi
source "$VENV/bin/activate"

TOWN_NAME="$1" TOWN_PASS="$2" python3 - <<'PYEOF'
import os, json, sys, bcrypt
from pathlib import Path

town     = os.environ["TOWN_NAME"]
password = os.environ["TOWN_PASS"]

towns_file = Path("towns.json")
if not towns_file.exists():
    print("towns.json not found.")
    sys.exit(1)

towns = json.loads(towns_file.read_text())
for t in towns:
    if t["town"] == town:
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        t["password_hash"] = pw_hash
        t.pop("password", None)   # remove plaintext if it existed
        towns_file.write_text(json.dumps(towns, indent=2))
        print(f"Password updated for town '{town}'. Restart the app to apply.")
        sys.exit(0)

print(f"Town '{town}' not found in towns.json.")
sys.exit(1)
PYEOF
