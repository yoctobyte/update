#!/usr/bin/env bash
# Set up the histsearch standalone environment
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"
echo "Installing dependencies..."
pip install -q --upgrade pip
pip install -q \
    requests \
    beautifulsoup4 \
    lxml \
    trafilatura \
    dateparser \
    playwright

echo "Installing Playwright browsers (for JS-enabled fetching)..."
playwright install chromium --with-deps 2>/dev/null || echo "  (Playwright browser install failed — JS fetching will be unavailable)"

echo ""
echo "Setup complete. Activate with: source histsearch/.venv/bin/activate"
echo "Then run: python histsearch.py --help"
