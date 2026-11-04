#!/usr/bin/env bash
# RavaaMD — installer otomatis lintas distro (idempoten, aman dijalankan ulang):
#   1. cek dependensi (python3, ffmpeg, node, yt-dlp) → pasang via package
#      manager terdeteksi: pacman | dnf | apt | zypper | apk
#   2. yt-dlp: utamakan ~/.local/bin/yt-dlp; bila binarnya di tempat lain →
#      symlink; bila hilang total → paket PM, gagal → biner statis GitHub
#   3. config yt-dlp `--js-runtimes node` (wajib untuk ekstraksi YouTube 2026)
#   4. daftar ke GNOME: launcher ~/.local/bin/ravaamd + ikon + ravaamd.desktop
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
BIN="$HOME/.local/bin/ravaamd"
DESK="$HOME/.local/share/applications/ravaamd.desktop"
YTDLP="$HOME/.local/bin/yt-dlp"
CFG="$HOME/.config/yt-dlp/config"

BIRU=$'\e[34m'; HIJAU=$'\e[32m'; KUNING=$'\e[33m'; MERAH=$'\e[31m'; NOL=$'\e[0m'
ok()    { echo "  ${HIJAU}✓${NOL} $*"; }
info()  { echo "  ${BIRU}•${NOL} $*"; }
warn()  { echo "  ${KUNING}!${NOL} $*"; }
gagal() { echo "  ${MERAH}✗${NOL} $*"; }
GAGAL=0

# ---------- 1. deteksi package manager ----------
PM=""
if   command -v pacman  >/dev/null 2>&1; then PM=pacman   # Arch / CachyOS / Manjaro
elif command -v dnf     >/dev/null 2>&1; then PM=dnf      # Fedora / RHEL
elif command -v apt-get >/dev/null 2>&1; then PM=apt      # Debian / Ubuntu
elif command -v zypper  >/dev/null 2>&1; then PM=zypper   # openSUSE
elif command -v apk     >/dev/null 2>&1; then PM=apk      # Alpine
fi
SUDO=""
if [ "$(id -u)" != 0 ] && command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"  # root langsung jalan tanpa sudo; non-root pakai sudo (minta password)
fi

pasang_paket() {  # $@ = nama paket
  [ -n "$PM" ] || return 1
  if [ "$(id -u)" != 0 ] && [ -z "$SUDO" ]; then
    warn "butuh root untuk memasang paket (sudo tidak tersedia)"
    return 1
  fi
  case "$PM" in
    pacman) $SUDO pacman -S --needed --noconfirm "$@" ;;
    dnf)    $SUDO dnf install -y "$@" ;;
    apt)    $SUDO apt-get update -qq && $SUDO apt-get install -y "$@" ;;
    zypper) $SUDO zypper --non-interactive install "$@" ;;
    apk)    $SUDO apk add "$@" ;;
    *)      return 1 ;;
  esac
}

butuh() {  # butuh <command> <paket-untuk-PM...> — cek, pasang bila hilang
  local cmd="$1"; shift
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$cmd — $(command -v "$cmd")"
    return 0
  fi
  if [ -z "$PM" ]; then
    gagal "$cmd tidak ada & tidak ada package manager terdeteksi — pasang manual dulu"
    GAGAL=$((GAGAL + 1)); return 1
  fi
  info "$cmd belum ada → memasang via $PM: $*"
  if pasang_paket "$@"; then
    ok "$cmd terpasang"
  else
    warn "$cmd gagal dipasang via $PM — pasang manual: $*"
    GAGAL=$((GAGAL + 1)); return 1
  fi
}

echo "RavaaMD installer — cek dependensi (PM terdeteksi: ${PM:-tidak ada})"

# python3 — Arch menyediakan "python" (dgn symlink python3); distro lain "python3"
if command -v python3 >/dev/null 2>&1; then
  ok "python3 $(python3 -V 2>&1 | awk '{print $2}')"
elif command -v python >/dev/null 2>&1 && python -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
  # Arch menyediakan python; wrapper python3 dibuat bila benar-benar absen
  ln -sf "$(command -v python)" "$HOME/.local/bin/python3" 2>/dev/null || true
  ok "python3 → $(python -V 2>&1 | awk '{print $2}') (symlink)"
else
  butuh python3 python3 || butuh python python || true
fi

butuh ffmpeg ffmpeg || true
butuh node nodejs || true

# node ≥ 22 = syarat sistem EJS yt-dlp (node 20 ditandai "unsupported")
if command -v node >/dev/null 2>&1; then
  major=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
  if [ "$major" -ge 22 ]; then
    ok "node $(node -v) (≥22, syarat EJS yt-dlp)"
  else
    warn "node $(node -v) < 22 → ekstraksi YouTube bisa lambat/gagal; pasang node 22+ (nvm / repositori resmi distro)"
  fi
fi

# ---------- 2. yt-dlp ----------
echo "Cek yt-dlp…"
if [ -x "$YTDLP" ]; then
  ok "$YTDLP ($($YTDLP --version 2>/dev/null || echo '?'))"
elif command -v yt-dlp >/dev/null 2>&1; then
  # biner ada di lokasi lain (mis. /usr/bin dari pacman) → samakan dgn ekspektasi aplikasi
  mkdir -p "$HOME/.local/bin"
  ln -sf "$(command -v yt-dlp)" "$YTDLP"
  ok "symlink $YTDLP → $(command -v yt-dlp)"
else
  if [ -n "$PM" ]; then
    info "yt-dlp belum ada → memasang via $PM…"
    pasang_paket yt-dlp || true
  fi
  if command -v yt-dlp >/dev/null 2>&1; then
    mkdir -p "$HOME/.local/bin"
    ln -sf "$(command -v yt-dlp)" "$YTDLP"
    ok "symlink $YTDLP → $(command -v yt-dlp)"
  else
    # fallback lintas distro: biner statis resmi (dipakai juga di Fedora user)
    mkdir -p "$HOME/.local/bin"
    info "yt-dlp tidak ada di PM → unduh biner statis ke $YTDLP"
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL -o "$YTDLP.tmp" https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp
    elif command -v wget >/dev/null 2>&1; then
      wget -q -O "$YTDLP.tmp" https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp
    else
      gagal "tidak ada curl/wget untuk mengunduh yt-dlp"; GAGAL=$((GAGAL + 1))
    fi
    if [ -f "$YTDLP.tmp" ]; then
      chmod +x "$YTDLP.tmp" && mv "$YTDLP.tmp" "$YTDLP"
      ok "yt-dlp statis $($YTDLP --version 2>/dev/null || echo '?') terpasang"
    fi
  fi
fi

# ---------- 3. config yt-dlp (WAJIB: --js-runtimes node) ----------
echo "Cek config yt-dlp…"
mkdir -p "$(dirname "$CFG")"
if [ ! -e "$CFG" ]; then
  echo "--js-runtimes node" > "$CFG"
  ok "config dibuat: $CFG"
elif grep -q -- "--js-runtimes" "$CFG"; then
  ok "config sudah memuat --js-runtimes"
else
  printf '\n--js-runtimes node\n' >> "$CFG"
  ok "flag --js-runtimes node ditambahkan ke config lama"
fi

# ---------- 4. daftar ke GNOME ----------
echo "Pasang launcher + ikon + entri menu…"
mkdir -p "$ICON_DIR" "$HOME/.local/bin" "$HOME/.local/share/applications"
cp "$DIR/icon.svg" "$ICON_DIR/ravaamd.svg"

# launcher — path absolut supaya .desktop tidak kehilangan cwd
cat > "$BIN.tmp" <<EOF
#!/usr/bin/env bash
exec python3 "$DIR/run.py" "\$@"
EOF
chmod +x "$BIN.tmp"
mv "$BIN.tmp" "$BIN"
ok "launcher: $BIN"

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
ok "entri menu: $DESK"

command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" || true
gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo ""
if [ "$GAGAL" -eq 0 ]; then
  echo "${HIJAU}Semua siap.${NOL} Buka lewat Activities (Super) → cari “RavaaMD”."
else
  echo "${KUNING}Selesai dengan $GAGAL catatan — lihat pesan ✗/! di atas, lalu jalankan lagi:${NOL} ./install.sh"
  exit 1
fi
