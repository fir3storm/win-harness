#!/bin/bash
# Global installer for win-harness
# Usage: bash install.sh [git-repo-url]
#
# After installation, the `win-harness` command is available globally.

set -e

REPO_URL="${1:-https://github.com/fir3storm/win-harness.git}"
INSTALL_DIR="${WIN_HARNESS_HOME:-$HOME/.win-harness}"

echo "[1/4] Cloning win-harness..."
if [ -d "$INSTALL_DIR" ]; then
    echo "   Already installed at $INSTALL_DIR, updating..."
    cd "$INSTALL_DIR"
    git pull --quiet
else
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

echo "[2/4] Installing Python package..."
pip install -e . --quiet

echo "[3/4] Verifying installation..."
if ! command -v win-harness &>/dev/null; then
    echo "[ERROR] win-harness command not found after install."
    echo "  Try: pip install -e . --user"
    exit 1
fi

echo "[4/4] Installation complete!"
echo ""
echo "  win-harness is now available globally."
echo "  Run: win-harness list"
echo "  Or: win-harness plan \"Your security task here\""
