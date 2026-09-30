#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# build-web.sh — macOS / Linux build script for the GroundZero Browser UI
#
# Produces a single double-click binary that starts a local web server and
# opens your browser automatically.  No Tkinter, no GUI framework required.
#
# Output: dist/GroundZero-Web-v<version>-mac   (macOS)
#         dist/GroundZero-Web-v<version>-linux (Linux)
#
# Optional code signing (macOS only):
#   export SIGN_IDENTITY="Developer ID Application: Your Org (TEAMID)"
#   export NOTARY_PROFILE="groundzero"    # set up with xcrun notarytool
#   ./build-web.sh
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$SCRIPT_DIR/groundzero" ]; then
    PROJECT_ROOT="$SCRIPT_DIR"
elif [ -d "$SCRIPT_DIR/../groundzero" ]; then
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
    PROJECT_ROOT="$SCRIPT_DIR"
fi
cd "$PROJECT_ROOT"

# Extract tool version dynamically from package
VERSION=$(python3 -c "from groundzero.constants import TOOL_VERSION; print(TOOL_VERSION)" 2>/dev/null || echo "7.2.0")

# Use platform-specific versioned name so downloads are unambiguous
if [ "$(uname)" = "Darwin" ]; then
    NAME="GroundZero-Web-v${VERSION}-mac"
else
    NAME="GroundZero-Web-v${VERSION}-linux"
fi
ENTRY="groundzero_web.py"
BUNDLE_ID="com.broadcom.groundzero-web"

SIGN_IDENTITY="${SIGN_IDENTITY:-}"
NOTARY_PROFILE="${NOTARY_PROFILE:-}"

echo "==> Checking Python..."
python3 --version

# No Tkinter check needed — the web UI has no GUI framework dependency.

echo "==> Checking / installing PyInstaller..."
if command -v pyinstaller &>/dev/null; then
    PYINSTALLER_CMD="pyinstaller"
elif python3 -m pyinstaller --version &>/dev/null; then
    PYINSTALLER_CMD="python3 -m pyinstaller"
else
    pip3 install --quiet "pyinstaller==6.*" --break-system-packages
    PYINSTALLER_CMD="pyinstaller"
fi
$PYINSTALLER_CMD --version

echo "==> Bundling documentation..."
python3 tools/bundle_docs.py

echo "==> Cleaning intermediate scratch files..."
rm -rf build "${NAME}.spec" GroundZero-Web*.spec
mkdir -p dist
rm -f "dist/${NAME}" "dist/${NAME}.zip" "dist/${NAME}-notarize.zip"

echo "==> Building ${NAME}..."
$PYINSTALLER_CMD \
    --onefile \
    --name "${NAME}" \
    --osx-bundle-identifier "${BUNDLE_ID}" \
    --collect-all groundzero \
    "${ENTRY}"

echo ""
if [ ! -f "dist/${NAME}" ]; then
    echo "[ERROR] Build did not produce dist/${NAME}"
    exit 1
fi

# Ensure the executable bit is set — macOS will open the file as a document
# in TextEdit if this bit is missing, so we set it explicitly regardless of
# what PyInstaller produces.
chmod +x "dist/${NAME}"
echo "==> Build complete:  dist/${NAME}"

# ---------------------------------------------------------------------------
# Code signing / notarization (macOS only, and only when certs are configured)
# ---------------------------------------------------------------------------
APP_BUNDLE="dist/${NAME}.app"
SIGN_TARGET="dist/${NAME}"
[ -d "$APP_BUNDLE" ] && SIGN_TARGET="$APP_BUNDLE"

if [ "$(uname)" = "Darwin" ] && [ -n "$SIGN_IDENTITY" ]; then
    echo ""
    echo "==> Signing ${SIGN_TARGET}"
    codesign --force --deep --timestamp \
             --options runtime \
             --sign "$SIGN_IDENTITY" \
             "$SIGN_TARGET"
    codesign --verify --strict --verbose=2 "$SIGN_TARGET"
    echo "    Signed OK."

    if [ -n "$NOTARY_PROFILE" ]; then
        echo ""
        echo "==> Notarizing..."
        ZIP="dist/${NAME}-notarize.zip"
        ditto -c -k --keepParent "$SIGN_TARGET" "$ZIP"
        if xcrun notarytool submit "$ZIP" \
                --keychain-profile "$NOTARY_PROFILE" --wait; then
            if [ -d "$APP_BUNDLE" ]; then
                xcrun stapler staple "$APP_BUNDLE" && echo "    Stapled OK."
            else
                echo "    Note: a --onefile binary cannot be stapled;"
                echo "          the notarization ticket is checked online instead."
            fi
        else
            echo "[WARN] Notarization failed."
        fi
        rm -f "$ZIP"
    else
        echo ""
        echo "    NOTARY_PROFILE not set — signed but not notarized."
    fi
else
    if [ "$(uname)" = "Darwin" ]; then
        echo ""
        echo "    Unsigned build. Users will see a Gatekeeper warning on first launch."
        echo "    They can bypass it with: right-click → Open → Open"
        echo ""
        echo "    If macOS opens the binary in TextEdit instead of running it, fix with:"
        echo "      chmod +x dist/${NAME}"
    fi
    xattr -dr com.apple.quarantine "dist/${NAME}" 2>/dev/null || true
    [ -d "$APP_BUNDLE" ] && \
        xattr -dr com.apple.quarantine "$APP_BUNDLE" 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# Launcher Script & Quick-Start Documentation
# ---------------------------------------------------------------------------
if [ "$(uname)" = "Darwin" ]; then
    echo ""
    echo "==> Generating macOS double-click launcher & instructions..."
    cat <<'EOF' > "dist/Launch-GroundZero-Web.command"
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
EOF
    chmod +x "dist/Launch-GroundZero-Web.command"

    cat <<EOF > "dist/HOW_TO_OPEN_ON_MAC.txt"
================================================================================
          GroundZero — VCF / vSphere 9.1 HCI Readiness (macOS)
                           Quick Start & Launch Guide
================================================================================

HOW TO LAUNCH ON macOS:
--------------------------------------------------------------------------------
Option 1 (Simplest — Double Click Launcher):
  Double-click 'Launch-GroundZero-Web.command'.
  This opens a Terminal window, starts the local web server, and automatically
  opens the Web UI in your default browser at:
  http://127.0.0.1:7182

Option 2 (Direct Executable):
  Open Terminal, navigate to this unzipped folder, and run:
    ./${NAME}

Option 3 (From Python Source):
  If you have Python 3.9+ installed:
    python3 scripts/groundzero_web.py

macOS GATEKEEPER / SECURITY NOTICE (FIRST LAUNCH ONLY):
--------------------------------------------------------------------------------
Because internal/field tools are not distributed through the Mac App Store,
macOS Gatekeeper will show a verification prompt on first launch:
  "Launch-GroundZero-Web.command cannot be opened because the developer
   cannot be verified."

To bypass this prompt (required only once on first launch):
  1. Right-click (or Control-click) 'Launch-GroundZero-Web.command' (or the binary).
  2. Select 'Open' from the context menu.
  3. Click 'Open' in the confirmation dialog.
  4. After doing this once, normal double-clicking will work every time.

Alternatively, via Terminal:
  xattr -cr .
  ./Launch-GroundZero-Web.command

FEATURES & USAGE:
--------------------------------------------------------------------------------
- Interactive browser interface for single/fleet server discovery and scanning.
- Evaluates CPU, BIOS/BMC firmware, NVMe storage, vSAN ESA, and NICs against VCF 9.1.
- Generates standalone self-contained HTML assessment reports.
- Automatically securely stores credentials in the macOS Keychain.
- Web UI Port: http://127.0.0.1:7182 (Click 'Quit' in header or press Ctrl+C to exit).
================================================================================
EOF
fi

echo ""
echo "==> Packaging release archive dist/${NAME}.zip..."
if [ "$(uname)" = "Darwin" ]; then
    MAC_STAGE=$(mktemp -d)
    cp "dist/${NAME}" "$MAC_STAGE/${NAME}"
    chmod +x "$MAC_STAGE/${NAME}"
    cp "dist/Launch-GroundZero-Web.command" "$MAC_STAGE/Launch-GroundZero-Web.command"
    chmod +x "$MAC_STAGE/Launch-GroundZero-Web.command"
    cp "dist/HOW_TO_OPEN_ON_MAC.txt" "$MAC_STAGE/HOW_TO_OPEN_ON_MAC.txt"
    ditto -c -k --norsrc "$MAC_STAGE" "dist/${NAME}.zip"
    rm -rf "$MAC_STAGE"
    echo "    Created dist/${NAME}.zip (includes launcher & instructions with +x permissions)"
else
    cat <<EOF > "dist/HOW_TO_RUN_LINUX.txt"
================================================================================
          GroundZero — VCF / vSphere 9.1 HCI Readiness (Linux)
                           Quick Start & Launch Guide
================================================================================

HOW TO LAUNCH ON LINUX:
--------------------------------------------------------------------------------
1. Ensure executable permissions:
     chmod +x ./${NAME}

2. Run the executable:
     ./${NAME}

3. Open your browser to http://127.0.0.1:7182 (if it does not open automatically).
================================================================================
EOF
    python3 -c "
import os, zipfile
z = zipfile.ZipFile('dist/${NAME}.zip', 'w', zipfile.ZIP_DEFLATED)
for fname in ('${NAME}', 'HOW_TO_RUN_LINUX.txt'):
    fpath = os.path.join('dist', fname)
    if os.path.exists(fpath):
        st = os.stat(fpath)
        zi = zipfile.ZipInfo.from_file(fpath, arcname=fname)
        zi.external_attr = (st.st_mode & 0xFFFF) << 16
        with open(fpath, 'rb') as f:
            z.writestr(zi, f.read())
z.close()
"
    echo "    Created dist/${NAME}.zip"
fi

echo ""
echo "==> Staging build into bin/..."
mkdir -p bin
cp "dist/${NAME}" "bin/${NAME}"
chmod +x "bin/${NAME}"
if [ "$(uname)" = "Darwin" ]; then
    cp "dist/Launch-GroundZero-Web.command" "bin/Launch-GroundZero-Web.command"
    chmod +x "bin/Launch-GroundZero-Web.command"
    cp "dist/HOW_TO_OPEN_ON_MAC.txt" "bin/HOW_TO_OPEN_ON_MAC.txt"
fi

echo ""
echo "==> Running post-build cleanup (retaining last 3 versions)..."
if [ "$(uname)" = "Darwin" ]; then
    CLEAN_PLATFORM="mac"
else
    CLEAN_PLATFORM="linux"
fi
python3 tools/clean_build_artifacts.py --keep 3 --platform "${CLEAN_PLATFORM}"

echo ""
if [ "$(uname)" = "Darwin" ]; then
    echo "    Double-click dist/Launch-GroundZero-Web.command to launch."
    echo "    Or:  ./dist/${NAME}"
    echo "    Or:  ./bin/GroundZero-Web-mac"
else
    echo "    Run:  ./dist/${NAME}"
    echo "    Or:  ./bin/GroundZero-Web-linux"
fi
