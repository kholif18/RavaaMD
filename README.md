# RavaaMD

Personal app to download songs/videos from YouTube as **MP3 or MP4**,
**with embedded title-artist tags + cover art** — so Amberol (or any player)
shows tracks correctly, without CLI and without ad-filled downloader sites.

*RavaaMD = **R**avaa **M**edia **D**ownloader.*


MP3 (default) is downloaded with the locked recipe:

```
-x --audio-format mp3 --audio-quality 0 --embed-metadata --embed-thumbnail --no-playlist
```

MP4 is downloaded without audio extraction (`-f best --merge-output-format mp4`)
so video + audio stay intact in the MP4 container, also with embedded metadata
and thumbnail.

## How to use

**Launcher button (easiest)** — after running `bash install.sh` once, open
*Activities* in GNOME and search for **RavaaMD** (blue-teal note icon), then Enter.

**From terminal**:

```bash
python3 ~/Projects/ytmp3-gui/run.py
```

then open `http://127.0.0.1:8637` in your default browser. To also listen on
LAN (from laptop/phone via IP, no auth):
`python3 run.py --host0.0.0.0` — see Deploy section.

In the GUI:

1. Type song title (e.g. `Keane Somewhere Only We Know`) **or** paste a
   YouTube URL. Choose **MP3** (default) or **MP4** with the toggle buttons
   next to the input box, then click **Download** (or Enter). Automatic search
   tries **YouTube Music first** for MP3 (audio-focused catalog), **YouTube
   first** for MP4 (video), falling back to the other if not found.
2. Progress bar + log show download progress; multiple downloads queue one at a
   time (MP3 and MP4 share the same queue).
3. **Choose quality before downloading:**
   * MP4 resolution: Best / 1080p / 720p / 480p / 360p (like y2mate)
   * MP3 bitrate: Best / 320k / 256k / 192k / 128k
4. **Tags are split automatically** after download: title goes to *title*,
   artist to *artist* (e.g. `Sugar` / `Maroon 5`) — so Amberol shows tracks
   neatly, not one clump like "Artist - Title (...)". Applies to both MP3
   and MP4.
5. Done? Click **Quit** to shut down the application properly.

## Requirements

- Python 3 (stdlib only — no pip needed)
- `yt-dlp` at `~/.local/bin/yt-dlp` + `~/.config/yt-dlp/config` containing
  `--js-runtimes node` (YouTube 2026 extraction)
- `ffmpeg`/`ffprobe` in PATH
- Node v22 (JS runtime for yt-dlp)

If downloads suddenly all fail: `yt-dlp -U`.

## Deploy on home server (Docker)

Image includes everything needed (python + ffmpeg + node + yt-dlp +
`--js-runtimes node` config pre-baked) — on the server, just need Docker:

```bash
cd ~/Projects/RavaaMD
docker compose up -d --build
# → app at http://127.0.0.1:8637  (build automatically runs test suite)
docker compose down            # stop
```

Important notes (tested e2e — real downloads via container over loopback AND
LAN IP):

- Compose uses `network_mode: host` + `--host 0.0.0.0`. Without both, regular
  Docker port-publish (`"8637:8637"`) **will not work** because the app only
  listens on loopback inside the container — this pattern is tested, do not
  change to regular port-publish.
- **Close the native GUI first** before `compose up` so the container gets
  port 8637 (if busy, app auto-falls back to 8638..8657 — tunnel would point
  to the wrong port).
- Server = pure converter: no music volume / `MUSIC_DIR`. Convert results stay
  in `RAVAAMD_WORK` (default `/tmp/ravaamd-work` in container) briefly, then
  are sent to the device via `/api/fetch` and deleted.
### Cara kerja

Browser di laptop/HP hanya **remote control**: ketik lagu, klik Unduh —
server yang **convert** (yt-dlp + ffmpeg), lalu MP3 langsung **terunduh ke
perangkatmu** seperti y2mate, dan dihapus dari server. Tak ada simpanan
disini, tak perlu pembersihan manual.

### Dua jalur akses

| Tempat | Alamat | Catatan |
|---|---|---|
| Di rumah (LAN) | `http://IP-SERVER:8637` (contoh: `http://192.168.100.4:8637`) | cepat, langsung, tanpa Cloudflare |
| Di luar rumah | `https://nama-domain-kamu` (tunnel dari dashboard Cloudflare) | **wajib** Access policy (email OTP) |

- IP server lihat di banner log container, atau `ip -4 addr show scope global`.
- Fedora/firewalld: cek port terbuka dengan `firewall-cmd --list-ports`;
  bila 8637 tidak ada di daftar, buka dulu:
  `sudo firewall-cmd --permanent --add-port=8637/tcp && sudo firewall-cmd --reload`
- **Tanpa login**: siapa pun di LAN bisa melihat/menghapus file dan
  mematikan aplikasi. Untuk akses internet SELALU lewat tunnel + Access —
  jangan port-forward router ke 8637.

### Sambungkan Cloudflare (dari dashboard kamu)

Arahkan tunnel / public hostname Cloudflare ke origin
`http://127.0.0.1:8637` di mesin yang sama tempat container berjalan.
**Wajib pasang Access policy (mis. login email OTP) di hostname itu** —
aplikasi punya endpoint hapus-file dan matikan-server, tanpa auth itu
berbahaya terbuka dari internet.

## Uji

```bash
python3 tests/api-test.py
```

## Lainnya

- RPC alias CLI (tanpa GUI): `ytmp3 "nama lagu"` — lihat `~/.local/bin/ytmp3`.
- Kontrak teknis untuk agent AI: `.opencode/agents/AGENTS.md`.
