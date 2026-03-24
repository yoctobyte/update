#!/usr/bin/env bash
# genenv.sh — generate (or regenerate) the .env file with a secure secret key.
# Run once after cloning, or again to rotate the secret key.
# Warning: rotating the key invalidates all active sessions.

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    read -rp ".env already exists. Overwrite and rotate secret key? [y/N] " confirm
    [ "$confirm" = "y" ] || [ "$confirm" = "Y" ] || { echo "Aborted."; exit 0; }
fi

SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")

cat > "$ENV_FILE" <<EOF
FLASK_SECRET_KEY=$SECRET
EOF

chmod 600 "$ENV_FILE"
echo "Created $ENV_FILE with a fresh secret key."
echo "Note: rotating the key logs out all active admin sessions."
