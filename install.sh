#!/data/data/com.termux/files/usr/bin/bash
# Orion Code installer for Termux
set -e
VERSION="3.13"
echo ""
echo "  Orion Code ${VERSION}"
echo ""

if [ -z "${PREFIX:-}" ]; then
  echo "This installer is for Termux."
  echo "Desktop: python3 orion_code.py"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SCRIPT_DIR/orion_code.py"
[ -f "$SRC" ] || { echo "orion_code.py missing"; exit 1; }

if ! command -v python3 >/dev/null 2>&1; then
  pkg update -y
  pkg install -y python
fi

pip install --user -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null \
  || pip install --user requests tenacity rich 2>/dev/null \
  || true

INSTALL_DIR="$HOME/.orion-code"
mkdir -p "$INSTALL_DIR"
cp -f "$SRC" "$INSTALL_DIR/orion_code.py"
chmod +x "$INSTALL_DIR/orion_code.py"
[ -f "$SCRIPT_DIR/orion_brain.py" ] && cp -f "$SCRIPT_DIR/orion_brain.py" "$INSTALL_DIR/"
[ -f "$SCRIPT_DIR/orion_tui.py" ] && cp -f "$SCRIPT_DIR/orion_tui.py" "$INSTALL_DIR/"
[ -f "$SCRIPT_DIR/soul_default.md" ] && cp -f "$SCRIPT_DIR/soul_default.md" "$INSTALL_DIR/"
[ -f "$SCRIPT_DIR/README.md" ] && cp -f "$SCRIPT_DIR/README.md" "$INSTALL_DIR/" 2>/dev/null || true

mkdir -p "$HOME/.orion-code/brain"
if [ ! -f "$HOME/.orion-code/brain/soul.md" ] && [ -f "$INSTALL_DIR/soul_default.md" ]; then
  cp -f "$INSTALL_DIR/soul_default.md" "$HOME/.orion-code/brain/soul.md"
fi

cat > "$PREFIX/bin/orion" << EOF
#!/data/data/com.termux/files/usr/bin/sh
exec python3 "\$HOME/.orion-code/orion_code.py" "\$@"
EOF
chmod +x "$PREFIX/bin/orion"
ln -sf "$PREFIX/bin/orion" "$PREFIX/bin/orion-code" 2>/dev/null || true

[ -d "$HOME/storage" ] || termux-setup-storage 2>/dev/null || true

echo "Installed. Run: orion"
echo "API key: https://aistudio.google.com/apikey"
