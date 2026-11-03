# ytmp3-gui

Aplikasi kasar-kasar pribadi untuk mengunduh lagu dari YouTube sebagai MP3
**lengkap dengan tag judul-artis + sampul tertanam** — jadi Amberol (atau
player lain) langsung menampilkan lagu dengan benar, tanpa pakai CLI dan
tanpa situs downloader penuh iklan.

Satu-satunya sihir di dalamnya: `yt-dlp` dijalankan dengan

```
-x --audio-format mp3 --audio-quality 0 --embed-metadata --embed-thumbnail --no-playlist
```

## Cara pakai

**Tombol launcher (paling gampang)** — setelah `bash install.sh` dijalankan
sekali, tekan tombol *Activities* di GNOME dan cari **ytmp3-gui** (ikon nota
biru-teal), lalu Enter.

**Dari terminal**:

```bash
python3 ~/Projects/ytmp3-gui/run.py
```

lalu membuka `http://127.0.0.1:8637` di browser default. Mau sekalian
dengar di LAN (akses dari laptop/HP lain via IP, tanpa auth):
`python3 run.py --host0.0.0.0` — lihat bagian Deploy.

Di dalam GUI:

1. Ketik nama lagu (contoh: `Keane Somewhere Only We Know`) **atau** tempel
   URL YouTube, klik **Unduh** (atau Enter). Pencarian otomatis mencoba
   **YouTube Music dulu** (trek resmi katalog) — kalau tidak ketemu, jatuh
   ke pencarian YouTube biasa.
2. Bar progres + log menunjukkan jalannya unduhan; beberapa unduhan
   diacak-antrian satu per satu.
3. **Tag dipisah otomatis** setelah unduhan: judul masuk kolom *title*,
   artis masuk kolom *artist* (mis. `Sugar` / `Maroon 5`) — jadi Amberol
   menampilkan lagu dengan rapi, bukan satu gumpal "Artis - Judul (...)".
4. Daftar **Pustaka** di kanan adalah isi folder musik yang aktif — tombol
   **Buka folder** membukanya di pengelola berkas (Nautilus).
5. Ganti folder tujuan lewat kotak **folder** lalu **Simpan** (disimpan
   otomatis untuk peluncuran berikutnya).
6. Selesai memakai? Klik **Keluar** untuk mematikan aplikasinya sungguhan.

## Syarat

- Python 3 (stdlib saja — tidak perlu pip)
- `yt-dlp` di `~/.local/bin/yt-dlp` + `~/.config/yt-dlp/config` berisi
  `--js-runtimes node` (ekstraksi YouTube 2026)
- `ffmpeg`/`ffprobe` di PATH
- Node v22 (runtime JS untuk yt-dlp)

Jika unduhan mendadak gagal semua: `yt-dlp -U`.

## Deploy di home server (Docker)

Image membawa semua yang dibutuhkan (python + ffmpeg + node + yt-dlp +
config `--js-runtimes node` sudah dibakar) — di server cukup ada Docker:

```bash
cd ~/Projects/ytmp3-gui
MUSIC_DIR="$HOME/Music/My Musics" docker compose up -d --build
# → app di http://127.0.0.1:8637  (build otomatis menjalankan suite tes)
docker compose down            # berhenti
```

Catatan penting (sudah teruji e2e — unduhan nyata lewat container via
loopback DAN via IP LAN):

- Compose memakai `network_mode: host` + `--host 0.0.0.0`. Tanpa keduanya,
  port-publish docker biasa (`"8637:8637"`) **TIDAK akan sampai** karena
  app hanya mendengar di loopback container — pola ini sudah teruji,
  jangan diubah ke port-publish biasa.
- **Tutup GUI native dulu** sebelum `compose up` supaya container mendapat
  port 8637 (kalau sibuk, aplikasi otomatis fallback ke 8638..8657 —
  tunnel jadi menunjuk port yang salah).
- Folder musik = variabel `MUSIC_DIR` di compose (di-mount ke `/music`).
- Tombol **Buka folder** tidak berfungsi di container (tanpa desktop) —
  kini muncul pesan jelas, bukan error.

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
