#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Launch-VCF-Readiness-Web.command — macOS Double-Click Launcher
# Starts the local VCF Readiness Web UI and opens your default browser.
# ---------------------------------------------------------------------------
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Locate the binary in current directory or bin/
BIN=""
for candidate in "$DIR"/VCF-Readiness-Web-v*-mac "$DIR"/VCF-Readiness-Web-mac "$DIR"/bin/VCF-Readiness-Web-mac "$DIR"/bin/VCF-Readiness-Web-v*-mac; do
    if [ -f "$candidate" ] && [ ! -d "$candidate" ]; then
        BIN="$candidate"
        break
    fi
done

if [ -z "$BIN" ]; then
    echo "========================================================================"
    echo " [ERROR] Could not find the VCF Readiness Web executable in:"
    echo "         $DIR"
    echo " Please make sure the VCF-Readiness-Web-*-mac binary is in this folder."
    echo "========================================================================"
    echo "Press Enter to exit..."
    read -r
    exit 1
fi

chmod +x "$BIN" 2>/dev/null || true
xattr -d com.apple.quarantine "$BIN" 2>/dev/null || true

echo "========================================================================"
echo " VCF / vSphere 9.1 HCI Readiness Assessment Tool — Browser Web UI"
echo "========================================================================"
echo " Starting local server at http://127.0.0.1:7182 ..."
echo " Your default browser will open automatically."
echo " To stop the server, press Ctrl+C in this window or click 'Quit' in UI."
echo "========================================================================"
exec "$BIN" "$@"
