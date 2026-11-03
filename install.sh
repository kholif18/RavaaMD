#!/usr/bin/env bash
# Pasang pintu akses GUI ke GNOME (tanpa sudo):
#   ~/.local/bin/ytmp3-gui              → launcher
#   ~/.local/share/icons/hicolor/…/ytmp3-gui.svg (ikon)
#   ~/.local/share/applications/ytmp3-gui.desktop  (muncul di Activities)
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
BIN="$HOME/.local/bin/ytmp3-gui"
DESK="$HOME/.local/share/applications/ytmp3-gui.desktop"

mkdir -p "$ICON_DIR" "$HOME/.local/bin" "$HOME/.local/share/applications"
cp "$DIR/icon.svg" "$ICON_DIR/ytmp3-gui.svg"

# launcher — link/eksekusi via path absolut supaya .desktop tidak kehilangan cwd
cat > "$BIN.tmp" <<EOF
#!/usr/bin/env bash
exec python3 "$DIR/run.py" "\$@"
EOF
chmod +x "$BIN.tmp"
mv "$BIN.tmp" "$BIN"

cat > "$DESK.tmp" <<EOF
[Desktop Entry]
Type=Application
Name=ytmp3-gui
GenericName=YouTube → MP3 Downloader
Comment=Unduh MP3 lengkap metadata + cover untuk Amberol
Exec=$BIN
Icon=ytmp3-gui
Terminal=false
Categories=AudioVideo;Network;
EOF
mv "$DESK.tmp" "$DESK"

command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" || true
echo "Pasang OK:"
echo "  • launcher : $BIN"
echo "  • activities: 'ytmp3-gui' (ikon nota biru-teal)"
