#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# build.sh — Wrapper shim for GroundZero Build
# Delegating to build-web.sh for the recommended Browser UI binary.
# ---------------------------------------------------------------------------
echo "==> Delegating build to build-web.sh (Browser UI binary)..."
echo ""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/build-web.sh" ]; then
    TARGET_BUILD="$SCRIPT_DIR/build-web.sh"
elif [ -f "$SCRIPT_DIR/../build-web.sh" ]; then
    TARGET_BUILD="$SCRIPT_DIR/../build-web.sh"
else
    TARGET_BUILD="$SCRIPT_DIR/build-web.sh"
fi
exec "$TARGET_BUILD" "$@"
