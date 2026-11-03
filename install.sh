#!/usr/bin/env bash
# Pasang pintu akses GUI ke GNOME (tanpa sudo):
#   ~/.local/bin/ravaamd                → launcher
#   ~/.local/share/icons/hicolor/…/ravaamd.svg (ikon)
#   ~/.local/share/applications/ravaamd.desktop  (muncul di Activities)
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
BIN="$HOME/.local/bin/ravaamd"
DESK="$HOME/.local/share/applications/ravaamd.desktop"

mkdir -p "$ICON_DIR" "$HOME/.local/bin" "$HOME/.local/share/applications"
cp "$DIR/icon.svg" "$ICON_DIR/ravaamd.svg"

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
Name=RavaaMD
GenericName=YouTube → MP3 Downloader
Comment=Ravaa Media Downloader — unduh MP3 lengkap metadata + cover untuk Amberol
Exec=$BIN
Icon=ravaamd
Terminal=false
Categories=AudioVideo;Network;
EOF
mv "$DESK.tmp" "$DESK"

command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" || true
echo "Pasang OK:"
echo "  • launcher : $BIN"
echo "  • activities: 'RavaaMD' (ikon nota biru-teal)"
