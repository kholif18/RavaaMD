# PLAN — Fitur Unduhan MP4 (RavaaMD)

> Status: **rencana** (belum diimplementasi). MP3 tetap default; resep yt-dlp MP3 terkunci TIDAK diubah.

## 1. Latar belakang & cakupan

RavaaMD saat ini hanya unduh **MP3** (resep terkunci:
`-x --audio-format mp3 --audio-quality 0 --embed-metadata --embed-thumbnail
--no-playlist`). Tujuan rencana ini: tambahkan opsi **MP4** (video) tanpa
merusak perilaku MP3 yang sudah ada, sehingga user bisa memilih format per
unduhan dari GUI.

**Di dalam cakupan:**
* Pemilihan format di UI (MP3 default / MP4) sebagai toggle di panel Unduh.
* Kirim `format` lewat `POST /api/download`; server validasi (`mp3`|`mp4`,
  default `mp3`).
* `Job` carries `format`; `_jalankan_ytdlp` bangun resep berbeda per format.
* Deteksi hasil file menurut ekstensi `.mp3` atau `.mp4` (bukan hardcode
  `.mp3`); `_retag_terpisah` disesuaikan per format.
* `GET /api/fetch` kirim `Content-Type: video/mp4` untuk `.mp4`,
  `audio/mpeg` untuk `.mp3`.
* Tes unit + e2e MP4 nyata (verifikasi lewat `ffprobe`: stream video +
  audio, container mp4, metadata title/artist terisi).

**Di luar cakupan (tidak sekarang):**
* Simpan file ke folder musik / pustaka (server tetap *converter murni*:
  hasil di folder kerja, dikirim via `/api/fetch`, lalu dihapus — sesuai
  keputusan 2026-11-03).
* Ubah resep MP3 yang terkunci.
* Fitur "Buka folder"/daftar pustaka yang disebutkan README tapi belum ada di
  kode aktual.

## 2. Perubahan per berkas

### app/jobs.py
* `Job.__init__(query, format="mp3")` — simpan `self.format`; validasi nilai
  di `JobManager.add`.
* `Job.to_dict()` — tambah `"format": self.format`.
* `JobManager.add(query, format="mp3")` — validasi `format in {"mp3","mp4"}`
  (server juga memvalidasi, ini lapisan kedua), lewatkan ke `Job`.
* `_run(job)` — panggil `self._jalankan_ytdlp(job, url, job.format)`.
* Deteksi hasil unduhan: ganti
  `f.lower().endswith(".mp3")` → cek ekstensi yang cocok dengan
  `job.format` (`.mp3` atau `.mp4`).
* `_jalankan_ytdlp(job, url, fmt)`:
  * **mp3 (tidak berubah):**
    `-x --audio-format mp3 --audio-quality 0 --embed-metadata
     --embed-thumbnail --no-playlist --newline
     --print after_move:VIDEO_ID:%(id)s -P <dir> -o "%(title)s.%(ext)s" <url>`
  * **mp4 (baru, tanpa `-x`):**
    `-f best --merge-output-format mp4 --embed-metadata --embed-thumbnail
     --no-playlist --newline --print after_move:VIDEO_ID:%(id)s -P <dir>
     -o "%(title)s.%(ext)s" <url>`
    (video + audio digabung ffmpeg ke container mp4; thumbnail disematkan
    oleh yt-dlp).
* `_retag_terpisah(job, hint)` — cabang per format:
  * **mp3:** eksisting (ffmpeg `-map 0:a:0 -map 0:v:0? -c copy`,
    timpa `title`/`artist` saja).
  * **mp4:** ffmpeg `-map 0:v:0 -map 0:a:0? -c copy -movflags +faststart`
    + `-metadata title=...` / `-metadata artist=...`; **skip** jaring
    cover fallback untuk mp4 (asumsi `--embed-thumbnail` yt-dlp sudah
    menempelkan cover; `ada_sampul` lama deteksi *video stream apa pun*,
    jadi untuk mp4 main video akan selalu terdeteksi — tidak berarti
    cover).
* `_run_fake(job)` — tulis file palsu sesuai format:
  `.mp3` = ID3 palsu (lama), `.mp4` = ftyp box palsu agar tes fetch
  dapat membedakan.

### app/server.py
* `POST /api/download` — baca
  `format = str(data.get("format", "mp3"))`; validasi
  `format in {"mp3","mp4"}`; jika salah → `400 {"error": ...}`;
  `ctx.jobs.add(q, format=format)`.
* `GET /api/fetch` — `Content-Type`:
  `video/mp4` bila nama berakhir `.mp4`, `audio/mpeg` bila `.mp3`,
  else `application/octet-stream`. Sisanya (disposition, filename,
  `selesai_fetch`) tidak berubah.

### app/tags.py (opsional, pemeliharaan)
* Tambah `ada_sampul_mp4(path)` yang cek
  `ffprobe -select_streams v -show_entries stream=disposition`
  ada `attached_pic=1` (untuk jaring cover mp4 di masa depan). Untuk rencana
  ini cukup ditambahkan sebagai fungsi siap pakai, belum dipanggil wajib.

### static/index.html
* Tambah **pilih format** di dalam `.baris-unduh` (sebelum tombol Unduh),
  segmented control 2 tombol: `MP3` (aktif default) dan `MP4`, plus input
  tersembunyi atau state JS. Contoh markah:
  ```html
  <div class="format-pilih" aria-label="Format unduhan">
    <button type="button" class="fmt-btn aktif" data-fmt="mp3">MP3</button>
    <button type="button" class="fmt-btn" data-fmt="mp4">MP4</button>
  </div>
  ```
* Update subtitel panel & chip: "...MP3 atau MP4 + tag + cover → ke perangkat".
* Brand teks topbar dapat ditambahkan "MP4" (kosmetik).

### static/app.js
* State `formatTerpilih = "mp3"`; klik tombol fmt-toggle ganti class
  `aktif` + update state.
* `unduh()` kirim `{ query, format: formatTerpilih }`.
* `liJob` / `tarikHasil` sudah bekerja dengan `job.file` yang bisa
  berakhir `.mp4` — tidak perlu diubah (download attribute & fetch blob
  agnostik ekstensi).

### static/style.css
* Tambah gaya `.format-pilih`, `.fmt-btn`, `.fmt-btn.aktif` (aksen brand
  saat aktif, agar jelas format mana yang dipilih).

### tests/api-test.py
* `FAKE_BYTES_MP3` (lama) + `FAKE_BYTES_MP4` (ftyp palsu).
* `test_03_download_kosong_ditolak` — tambah kasus `format` invalid → 400.
* `test_05_siklus_job_fake_lalu_fetch` — tambah varian MP4:
  POST `format: mp4` → file `.mp4`, fetch status 200,
  `Content-Type: video/mp4`, isi = `FAKE_BYTES_MP4`, folder kerja kosong
  setelah fetch.
* Tes MP3 yang ada tetap harus hijau (tidak ada regresi).

### Dokumen yang perlu update (tidak mengubah kode)
* `AGENTS.md` (§3 peta file, §4 kontrak API, §5 batasan resep, §7 DoD,
  §8 masalah baru mp4).
* `README.md` — dokumentasikan opsi format MP4 di GUI.

## 3. Urutan implementasi (checklist)

1. [ ] Cabang git baru: `fitur/mp4`.
2. [ ] Ubah `app/jobs.py` (Job.format, resep mp4, deteksi ekstensi, retag
   cabang, fake mp4).
3. [ ] Ubah `app/server.py` (validasi format, content-type fetch).
4. [ ] (Opsional) `app/tags.py` — `ada_sampul_mp4`.
5. [ ] Ubah `static/index.html`, `static/app.js`, `static/style.css`
   (pilih format di UI).
6. [ ] Update `tests/api-test.py` (mp3 + mp4; format invalid → 400).
7. [ ] `python3 tests/api-test.py` → **hijau** (tanpa jaringan, mode FAKE).
8. [ ] E2E nyata: unduh video contoh sebagai MP4, verifikasi dengan
   `ffprobe` (≥1 stream video, ≥1 stream audio, container mp4, judul +
   artis metadata terisi, bitrate audio wajar bukan 128 kbps saja).
9. [ ] Bersihkan folder ujian (`/tmp/opencode/...` atau env `RAVAAMD_WORK`
   sendiri).
10. [ ] Commit + push ke `main`.

## 4. Risiko & catatan penting

* Resep MP3 **terkunci** — tidak boleh diubah, dihapus, atau dicampur ke
  resep MP4.
* Semua subprocess = **argv list** (tidak ada `sh -c` / f-string command);
  judul dengan apostrof/emoji aman.
* Satu worker yt-dlp tetap berlaku — MP3 dan MP4 antre dalam **satu**
  antrian FIFO, tidak paralel.
* Untuk MP4 jangan sertakan `-x` (extract audio).
* `ada_sampul` lama deteksi stream video apapun; untuk MP4 main video
  akan terdeteksi padahal belum tentu cover — jangan gunakannya sebagai
  penanda cover untuk MP4 tanpa pemeriksaan `attached_pic`.
* `AGENTS.md §5` dilarang menambah dependency; MP4 tidak butuh dependensi
  baru (ffmpeg sudah ada untuk merge video+audio).

## 5. Definition of Done

* [ ] Suite tes `python3 tests/api-test.py` hijau (termasuk kasus MP4 dan
  format invalid ditolak).
* [ ] E2E MP4 nyata lulus verifikasi `ffprobe` (video + audio, metadata
  judul/artis terisi, ukuran wajar).
* [ ] UI: pilih MP4 terlihat aktif, unduhan MP4 muncul sebagai `.mp4`,
  fetch mengembalikan `video/mp4`.
* [ ] `AGENTS.md` dan `README.md` terkini.
