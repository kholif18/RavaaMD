# AGENTS.md — RavaaMD (proyek TERPISAH dari Ravaa-POS)

> WAJIB dibaca sebelum menyentuh repo ini. Proyek ini BERDIRI SENDIRI —
> dilarang menyentuh `~/Projects/Ravaa-POS-v2` dari sesi agent ini (dan
> sebaliknya sesi Ravaa-POS dilarang menyentuh folder ini). Keduanya punya
> AGENTS.md sendiri supaya fokus agent tidak bercampur.
>
> Prinsip kerja: BUKTI DULU SEBELUM KLAIM. Setiap perilaku yang ditulis di
> file ini pernah diverifikasi langsung di laptop user (Fedora/GNOME, zsh,
> Python 3.14.8, node v22.23.1, ffmpeg 8.1.3).

## 1. Konteks & alasan proyek ini ada (jangan dilanggar)

* User memutar musik dengan **Amberol** — Amberol SECARA DESAIN hanya membaca
  metadata tertanam (ID3), tidak pernah menampilkan nama file. Downloader web
  (y2mate & serupa) TIDAK menulis tag apa pun (128 kbps, tanpa metadata).
  Akibatnya lagu tampil kotor/tanpa judul-artis-sampul di Amberol.
* Satu-satunya jawabannya: unduhan harus menghasilkan MP3 yang **memiliki tag
  + cover tertanam sendiri**, bukan mengandalkan nama file. Itulah alasan
  resep yt-dlp di bawah DIKUNCI — kehilangan `--embed-metadata` atau
  `--embed-thumbnail` = kembali ke masalah awal.
* GUI dipilih berupa **web app lokal** (bukan tkinter — Python user TANPA
  pip dan TANPA tkinter; bingkai lain dilarang, lihat §5). Backend Python
  **stdlib saja**, frontend HTML/CSS/JS vanilla, semua offline (tanpa CDN).
* User叮嘱: GUI = "tidak pakai CLI dari sisi user". Jalur CLI `~/.local/bin/ytmp3`
  tetap ada sebagai KESEKUNDER untuk user yang mau cepat — jangan dihapus,
  dan jangan mengubah file itu kecuali diminta (kepunyaan sesi kerja lain).

## 2. Toolchain yang TELAH TERPASANG (fakta, bukan tebakan)

* `yt-dlp` v2026.10.26 — binary statis di `~/.local/bin/yt-dlp`
  (dipilih `yt-dlp_linux`). Upgrade: `yt-dlp -U` (YouTube sering berubah —
  ini langkah pertama saat unduhan mendadak gagal semua).
* `~/.config/yt-dlp/config` berisi **satu baris**: `--js-runtimes node`.
  TANPA INI ekstraksi YouTube 2026 GAGAL dengan
  "No supported JavaScript runtime could be found". Node v22 ada di
  `/usr/bin/node`; `deno` TIDAK ada. Jangan hapus/timpa config itu.
* `ffmpeg` 8.1.3 di PATH (dibutuhkan yt-dlp untuk `-x` + embed metadata/
  thumbnail, dan ffmpeg untuk remux retag title/artist).
* `~/.local/bin/ytmp3` = wrapper CLI (auto-`ytsearch1:` untuk input non-URL,
  folder default `$HOME/Music/My Musics`, override satu kali via `YTMP3_DIR`).
* Pencarian YouTube Music: yt-dlp TIDAK punya `ytmsearch` (diverifikasi
  2026-10-26). Karena itu `app/jobs.py` memanggil API InnerTube
  `music.youtube.com/youtubei/v1/search` (client WEB_REMIX, stdlib
  urllib) sendiri, memakai stdlib saja. Struktur respons: item =
  `musicResponsiveListItemRenderer` + `watchEndpoint.videoId` +
  `musicVideoType` (ATV = trek resmi katalog Music, UGC = unggahan biasa).
* `xdg-open` ada (dipakai `GET /api/open-folder`).
* Path pustaka musik user: `/home/enma/Music/My Musics` (ADA SPASI di nama
  folder — semua path harus lewat argv list / shell-quote, jangan concat
  string mentah). 14 MP3 di folder itu sudah tertag + bersampul hasil kerja
  manual — JANGAN retag/ubah tanpa permintaan eksplisit.

## 3. Peta file (sumber kebenaran)

```
run.py                 Pintu masuk. argparse (--port 8637,
                       --host, --no-browser, --print-port, --folder),
                       ThreadingHTTPServer
                       di --host (DEFAULT 127.0.0.1;0.0.0.0 = akses LAN HANYA
                       atas permintaan user, lihat §5; banner tampilkan IP LAN
                       lewat _ip_lan()) + buka browser (webbrowser SETELAH
                       bind sukses, timer 0.4s). FOLDER TUJUAN hasil unduhan
                       (dikembalikan 2026-11-04): default ~/Music/My Musics,
                       pilihan terakhir disimpan config (CFG_DIR =
                       env RAVAAMD_CONFIG_DIR atau ~/.config/ravaamd;
                       config.json {"folder": ...}); muat_folder() cek isdir
                       sebelum pakai. Hasil kerja tetap di env RAVAAMD_WORK
                       (folder kerja per-job), dipindah ke folder tujuan saat
                       job selesai.
app/__init__.py        Menyimpan RESEP yt-dlp yang dikunci (dokumen inti).
app/jobs.py            Job + JobManager. SATU worker thread (antrian FIFO,
                       urutan dijamin dijalankan sekaligus SEBELUM
                       ThreadingHTTPServer dijadikan pembunuh konsistensi);
                       parse_progress() = regex "(\d+(\.\d+)?)% of" —
                       yt-dlp haruh "baris progres" MEMERLUKAN `--newline`
                       dan larang `--no-progress` (bug nyata: pasangan itu
                       MEMATIKAN bar progres GUI). Env:
                       RAVAAMD_FAKE=1  = siklus job tanpa jaringan (tests),
                       RAVAAMD_YTDLP=x = ganti path yt-dlp.
                       RANTAI PENCARIAN (input non-URL): URL eksplisit =
                       apa adanya; kalau bukan URL → cari_ytm() (InnerTube
                       YTM, prefer item ATV) dulu, kalau None/gagal →
                       `ytsearch1:`. Kalau unduhan YTM gagal exit≠0, job
                       dicoba ulang sekali dengan `ytsearch1:`.
                       RETAG: setelah unduhan sukses, _retag_terpisah()
                       remux ffmpeg (-c copy, sampul APIC ikut) hanya
                       menimpa tag title/artist jadi TERPISAH
                       ("Sugar"/"Maroon 5", bukan "Maroon 5 - Sugar
                       (Official Music Video)"). FAKE mode: retag DILEWATI
 PEMISAHAN MODUL: app/ytm.py + app/tags.py adalah satu-satunya helper
                         (jobs.py = antrian + orkestrasi yt-dlp saja) — JANGAN
                         digabung lagi.
app/ytm.py            cari_ytm() + _runs_text()/_telusuri_items(): cari di
                       katalog YouTube Music via InnerTube WEB_REMIX (stdlib
                       urllib). Prefer item ATV; None bila gagal → pemanggil
                       fallback `ytsearch1:` (rantai tetap di jobs.py).
app/tags.py           Helper tag/cover murni (argv list, tanpa state):
                       bagi_judul(), bersih_judul() (buang label promosi di
                       kurung; "(Kygo Remix)" dipertahankan), baca_tag() /
                       ada_sampul() (ffprobe), unduh_sampul() (JPEG
                       i.ytimg.com = jaring pengaman cover).
                       yang sah (dipakai guard /api/remove juga).
app/server.py          Build_handler(ctx): statis + API JSON. Ctx(folder,
                       jobs, simpan_folder). Kontrak eksak lihat §4.
static/index.html      Kerangka UI (topbar, kartu Unduh, kartu Pustaka,
                       modal, toasts). DILARANG inline <style>/style= —
                       semua gaya lewat link style.css.
static/style.css       Design system gelap (token di :root; aturan global
                       `[hidden] { display:none !important }` WAJIB ada —
                       lihat §8).
static/app.js          Polling /api/state tiap 800 ms → render ulang penuh;
                       semua listener dipasang di DOMContentLoaded, TIDAK
                       ada onclick inline; esc() WAJIB dipakai untuk semua
                       teks user/YT yang dirender.
icon.svg               Ikon nota biru-teal untuk .desktop.
install.sh             Installer lintas distro (idempoten, AMAN dijalankan
                       ulang): deteksi PM (pacman|dnf|apt|zypper|apk) → pasang
                       python3/ffmpeg/node bila hilang (butuh sudo utk paket);
                       yt-dlp: pakai ~/.local/bin/yt-dlp, symlink bila biner di
                       tempat lain, fallback unduh biner statis GitHub;
                       bikin config `--js-runtimes node` (append bila config
                       lama belum punya); baru daftar launcher
                       ~/.local/bin/ravaamd + ikon hicolor + entri
                       ravaamd.desktop. Exit 1 bila ada dependensi gagal.
tests/api-test.py      unittest stdlib; menyalakan run.py dengan
                       RAVAAMD_FAKE=1 + --folder & RAVAAMD_CONFIG_DIR
                       terisolasi (tempfile) di port bebas ACAK; 11 kasus
                       (index, bentuk state + folder, download kosong 400,
                       fetch id invalid, siklus job fake + fetch, parse_progress,
                       validasi format/quality, pilih folder (/api/folder),
                       bagi_judul/bersih_judul (import dari app.tags)).
README.md              Ringkasan pemakaian untuk user (Bahasa Indonesia).
```

Arah pakai: user membuka sesi agent di folder ini; `RavaaMD` (GUI) dan
`ytmp3` (CLI) adalah DUA pintu yang berbeda: GUI menyimpan hasil ke FOLDER
TUJUAN pilihan user (default ~/Music/My Musics, ganti via /api/folder atau
`--folder`); CLI (`~/.local/bin/ytmp3`) menulis ke folder musik via
YTMP3_DIR. Keduanya terpisah — jangan campur mekanisme config-nya.
job GUI harus jalan dulu sebelum CLI lain memutar file supaya tidak berebut.

## 4. Kontrak API internal (eksak — endpoint tidak boleh berisiko)

* `GET /` + `/static/*` — file dari `static/`; guard traversal (ASCII path
  berawalan STATIC_DIR + os.sep). Mime dipecah dari AKHIRAN_STATIS.
* `GET /api/state` -> `{current, queue, history, folder}` — SATU sumber untuk
  seluruh UI; `current` null saat nganggur; `folder` = path ABSOLUT folder
  tujuan hasil unduhan (pilihan user, diganti via POST /api/folder).
* `POST /api/folder` `{folder}` -> `{ok, folder}` — 400 bila kosong, path
  relatif, atau bukan folder yang ada. Mengubah ctx.folder + jobs.folder +
  menyimpan config (simpan_folder). File lama TIDAK PERNAH tertimpa: nama
  bentrok di folder tujuan diberi suffix " (2)", " (3)" …
* `GET /api/open-folder` -> `{ok, folder}` — `xdg-open` argv-list ke folder
  tujuan; 500 bila xdg-open tak ada.
* `GET /api/fetch?id=N` — kirim SALINAN hasil convert ke browser; file di
  folder tujuan TIDAK dihapus (milik user). Hanya folder kerja sisa (fallback
  bila pemindahan gagal) yang dibuang setelah transfer penuh.
* `POST /api/download` `{query}` -> 201 `{ok, job}` — 400 bila kosong atau
  > 300 char. Non-URL dicari di YouTube Music dulu (cari_ytm di app/ytm.py,
  prefer trek ATV resmi) lalu fallback `ytsearch1:` — rantai di jobs.py
  (BUKAN di server), URL persis dihadapkan apa adanya.
* `POST /api/cancel` `{}` -> `{ok, batal}` — batal=false bila tidak ada
  proses jalan (BUKAN error).
* `POST /api/shutdown` `{}` -> 200 lalu shutdown thread terpisah
  (memanggil server.shutdown() dari DLM handler = deadlock). Body nol byte
  dilarang? TIDAK untuk route ini: shutdown DIPERBOLEHKAN tanpa body (UI
  mengirim `{}`, tapi jangan menolak bila kosong).
* Bentuk job (to_dict): `{id, query, status: pending|running|done|error|
  canceled, percent|null, exitcode|null, file|null, lines:[..]}`.
  `percent` hanya terisi bila regex kena; `history` maks 10 (deque).

## 5. Batasan perubahan (anti-merusak)

* DILARANG menambah dependency apa pun (pip/pipx/npm/CDN/font eksternal/repo
  git). Python stdlib + vanilla JS adalah keputusan sadar (mesin user TIDAK
  punya pip; semua harus jalan offline).
* RESEP yt-dlp DIKUNCI: `-x --audio-format mp3 --audio-quality 0
  --embed-metadata --embed-thumbnail --no-playlist` — menghilangkan salah
  satu flag = fitur proyek rusak. `--newline` wajib tetap ada setelahnya;
  DILARANG menambah `--no-progress` kembali. Retag _terpisah() adalah
  LANGKAH TAMBAHAN SETELAH yt-dlp (remux `-c copy` yang hanya menimpa
  title/artist) — jangan menyelipkannya ke dalam resep.
* Bind DEFAULT 127.0.0.1 JANGAN diubah diam-diam. Akses LAN = flag
  `--host0.0.0.0` yang SUDAH DISETUJUI user (2026-11-03: home server —
  LAN via IP untuk akses cepat, internet lewat tunnel Cloudflare) —
  TANPA auth; risiko "siapa pun di LAN bisa lihat/hapus" diterima user
  untuk LAN rumah. Docker/compose DICABUT (2026-11-04) — app hanya
  berjalan native, flag itu dipakai langsung di `python3 run.py --host 0.0.0.0`.
  Kalau user minta auth atau skenario exposure lain, diskusi dulu.
* DILARANG memanggil shell lewat string (`sh -c`, f-string command):
  semua subprocess = argv list; query/lagu apa pun aman.
* DILARANG membuat job berjalan paralel — worker tunggal = satu kernel yt-dlp
  (alasan sederhana dan cukup: antrian FIFO membuat urutan fairness; paralel
  menggandakan risiko rate-limit YouTube).
* Hapus file via GUI HARUS tetap lewat confirmDialog di app.js + guard
  basename di server. Jangan pernah percepat dengan memanggil os.remove di
  route lain tanpa guard.
* Jangan menyentuh `~/Projects/Ravaa-POS-v2` (sesi masing-masing terpisah),
  `~/.local/bin/yt-dlp`, `~/.config/yt-dlp/config`, `~/.local/bin/ytmp3`
  tanpa alasan kuat + konfirmasi user — itu milik workflow CLI yang sudah
  bekerja.
* Jangan menulis ulang 14 file MP3 di `~/Music/My Musics` (tag/cover sudah
  benar). Uji unduhan selalu ke folder kecil sendiri (mis. `/tmp/opencode/
  gui-test`) lalu RAPIS setelah selesai.
* `install.sh` idempoten; jika mengubah struktur, pastikan jalankan ulang
  TIDAK menumpuk (launcher dibuat .tmp lalu mv).
* GUI polling 800 ms = konstanta di app.js; jangan dibiarkan tanpa kondisi —
  bila state error, biarkan tampil, JANGAN flush penuh DOM sepanjang waktu.

## 6. Perintah (eksak)

```bash
cd ~/Projects/RavaaMD
python3 run.py                     # GUI -> http://127.0.0.1:8637 (fallback +1..+20), browser otomatis
python3 run.py --no-browser        # untuk pengujian (tests/ dan curl)
python3 run.py --no-browser --print-port
python3 run.py --host 0.0.0.0 --no-browser   # dengar di LAN juga (tanpa auth, §5)
python3 run.py --folder /tmp/opencode/gui-test --no-browser --print-port   # paksa folder tujuan hasil unduhan
python3 tests/api-test.py          # unittest, env RAVAAMD_FAKE=1 otomatis, tanpa jaringan
bash install.sh                    # cek+pasang dependensi (PM terdeteksi) + launcher + .desktop + ikon (idempoten)
~/.local/bin/ravaamd             # launcher GUI (setelah install.sh)
# upgrade downloader bila unduhan mendadak gagal semua:
yt-dlp -U
# git (repo publik, init 2026-11-03): remote git@github.com:kholif18/RavaaMD.git
git push                        # branch main; commit dulu dengan pesan jelas
```

Port: 8637 default (fallback +1 s/d +20). DILARANG pindah default tanpa
update run.py + AGENTS ini + README.

ENV: RAVAAMD_WORK = folder kerja per-job; RAVAAMD_FAKE = mode tes;
RAVAAMD_YTDLP = path yt-dlp; RAVAAMD_CONFIG_DIR = lokasi config folder
tujuan (default ~/.config/ravaamd — dipakai tests/ supaya config user
tidak tertimpa).

## 7. Definition of Done (fitur dianggap selesai bila)

1. Kode konsisten dengan §3/§4 (peta & kontrak tidak tertinggal).
2. `python3 tests/api-test.py` hijau.
3. Setiap endpoint baru diuji dengan curl NYATA dan output ditempel di jawaban.
4. Unduhan e2e (mode nyata, bukan FAKE) DIUJI minimal sekali saat fitur
   unduhan berubah: periksa file dengan `ffprobe` — title/artist tag +
   attached_pic cover + bitrate ±256 kbps bukan 128.
5. Tidak ada port/ENV baru tanpa didokumentasikan di §2/§6.

## 8. Masalah yang pernah & sudah beres (jangan ulangi)

> **DICABUT 2026-11-04:** Docker/compose dihapus atas permintaan user —
> RavaaMD kembali berjalan NATIVE di laptop/PC (desain awal). Entri di bawah
> yang menyinggung container/compose adalah catatan HISTORIS; jangan
> menghidupkannya kembali kecuali user minta.

* `--no-progress` bersama `--newline` MEMATIKAN bar progres GUI → sudah
  dihapus, jangan dikembalikan.
* `_run(job)` tanpa folder = TypeError (folder sekarang disimpan di
  JobManager dan ikut diubah oleh /api/folder).
* CSS `#2230592` (7 digit) → `#22305a` (valid 3-digit pair).
* Kode mati di app.js render() dan guard mati di server.py /api/remove
  sudah dibuang.
* Tidak adanya JS runtime → config `--js-runtimes node` (lihat §2).
* Tag gumpal ("Maroon 5 - Sugar (Official Music Video)" sebagai satu
  judul) → retag _retag_terpisah() memisah title/artist setelah unduhan;
  e2e 2026-11-03: Sugar.mp3 = title "Sugar" + artist "Maroon 5" + album
  "V" + sampul utuh + 271 kbps.
* Ikon default di Files untuk unduhan baru → GNOME meng-cache status
  "gagal" thumbnail (fail-cache ~/.cache/thumbnails/fail/**) dan tidak
  pernah mencoba ulang → bersihkan_cache_gagal() membuang entri itu saat
  job selesai; Nautilus men-thumbnail ulang otomatis (terverifikasi:
  Dua Lipa Training Season kini punya thumbnail::path normal).
* `gst-audio-thumbnailer` panik "NotFound" = folder OUTPUT-nya hilang
  (bukan file rusak) — jangan salah diagnosa; cek `ls` folder output dulu.
* Modal/kendala tampil terus walau atribut `hidden` ada → gaya kelas
  (`.modal{display:grid}`, `.btn{display:inline-flex}`) MENIMPA gaya UA
  `[hidden]{display:none}` (author > UA stylesheet) → wajib pertahankan
  aturan global `[hidden] { display: none !important }` di style.css
  (bug nyata 2026-11-03: dialog konfirmasi kosong selalu terlihat).
* Screenshot UI: Firefox `--screenshot` bisa jepret SEBELUM poll /api/state
  pertama selesai (pustaka "memuat…") — pakai
  `google-chrome --headless --virtual-time-budget=6000 --screenshot=…`
  yang menunggu timer/jaringan selesai.
* Container + port-publish docker (`-p 8637:8637`) TIDAK sampai bila app
  bind `127.0.0.1` DI DALAM container (docker-proxy menuju IP eth0 →
  connection refused; gejalanya "Connection reset" di host) — pola benar:
  `network_mode: host` (app tetap loopback-only, tunnel → 127.0.0.1:8637).
  JANGAN salah diagnosa jadi firewalld — bukti: `curl` ke eth0 container
  dari dalam container sendiri juga refused.
* Healthcheck container JANGAN hardcode port 8637: run.py boleh fallback
  8637..+20 (mis. GUI native ikut jalan) → scan rentang:
  `for p in $(seq 8637 8657); do curl …/$p/api/state && exit 0; done`.
* e2e container teruji 2026-11-03: unduhan nyata `maroon 5 sugar` lewat
  compose → Sugar.mp3 (title/artist/album benar, cover png, 278 kbps),
  yt-dlp 2026.10.26 + node v20.19.2 di dalam image, build gate 8/8.
* Akses LAN (disetujui user 2026-11-03): compose = `network_mode: host` +
  `--host0.0.0.0` — teruji curl + unduhan nyata via http://192.168.100.4:8637
  (Keane → "Somewhere Only We Know"/"Keane", cover png, 272 kbps). firewalld
  mesin user sudah buka rentang 1025-65535/tcp (8637 termasuk); di mesin
  lain cek `firewall-cmd --list-ports` dulu sebelum menyalahkan aplikasi.
