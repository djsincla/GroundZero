#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Launch-GroundZero-Web.command — macOS Double-Click Launcher
# Starts the local GroundZero Web UI and opens your default browser.
# ---------------------------------------------------------------------------
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Locate the binary in current directory or bin/
BIN=""
for candidate in "$DIR"/GroundZero-Web-v*-mac "$DIR"/GroundZero-Web-mac "$DIR"/bin/GroundZero-Web-mac "$DIR"/bin/GroundZero-Web-v*-mac; do
    if [ -f "$candidate" ] && [ ! -d "$candidate" ]; then
        BIN="$candidate"
        break
    fi
done

if [ -z "$BIN" ]; then
    echo "========================================================================"
    echo " [ERROR] Could not find the GroundZero Web executable in:"
    echo "         $DIR"
    echo " Please make sure the GroundZero-Web-*-mac binary is in this folder."
    echo "========================================================================"
    echo "Press Enter to exit..."
    read -r
    exit 1
fi

chmod +x "$BIN" 2>/dev/null || true
xattr -d com.apple.quarantine "$BIN" 2>/dev/null || true

echo "========================================================================"
echo " GroundZero — VCF / vSphere 9.1 HCI Readiness — Browser Web UI"
echo "========================================================================"
echo " Starting local server at http://127.0.0.1:7182 ..."
echo " Your default browser will open automatically."
echo " To stop the server, press Ctrl+C in this window or click 'Quit' in UI."
echo "========================================================================"
exec "$BIN" "$@"
