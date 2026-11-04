"""Antrian unduhan — eksekusi yt-dlp SATU job sekaligus (urutan memakai lock).

Server = CONVERTER MURNI (keputusan user 2026-11-03): hasil convert tinggal di
folder kerja per-job, dikirim ke perangkat peminat lewat `GET /api/fetch`,
lalu DIHAPUS — tidak ada hasil yang disimpan di server (tak ada pembersihan
manual). Folder kerja dibuang juga saat: start (sisa crash), job gagal/batal,
dan job keluar dari history (overflow).

Invarian yang dijaga (lihat AGENTS.md §5):
  * HANYA satu process yt-dlp jalan bersamaan; job berikutnya menunggu.
  * Argumen URL dipindah lewat argv list (bukan command string), jadi
    judul dengan apostrof/quote/emoji apa pun aman dari shell injection.
  * Gagal = job.status "error" + exitcode; TIDAK PERNAH melempar ke caller.

Pencarian per format (keputusan user):
  * MP3: YouTube Music dulu (audio terfokus), lalu fallback YouTube biasa.
  * MP4: YouTube biasa dulu (video), lalu fallback YouTube Music.

Modul tetangga (dipisah supaya file ini mudah dirawat — jangan digabung lagi):
  * app/ytm.py    — cari_ytm(): pencarian katalog YouTube Music (InnerTube).
  * app/tags.py   — bersih_judul/bagi_judul/baca_tag/ada_sampul/unduh_sampul.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from urllib.parse import urlencode, urlunparse, urlparse, parse_qs

from .tags import (ada_sampul, baca_tag, bagi_judul, bersih_judul,
                   unduh_sampul)
from .ytm import cari_ytm

YT_DLP = os.environ.get("RAVAAMD_YTDLP", os.path.expanduser("~/.local/bin/yt-dlp"))
FAKE = os.environ.get("RAVAAMD_FAKE") == "1"  # dipakai tests/ (tanpa jaringan)

# baris progres yt-dlp: "[download]  42.5% of    4.00MiB at  2.11MiB/s ETA 00:02"
RE_PROG = re.compile(r"(\d+(?:\.\d+)?)% of")
LOG_MAXLEN = 500  # baris nyata disimpan per job (deque)

FORMAT_VALID = {"mp3", "mp4"}
FORMAT_DEFAULT = "mp3"

# Pilihan kualitas per format (diterima dari UI / API)
MP4_RESOLUSI = {"best", "1080p", "720p", "480p", "360p"}
MP3_BITRATE = {"best", "320k", "256k", "192k", "128k"}
QUALITY_DEFAULT = "best"


def bersih_url_youtube(url: str) -> str:
    """Hapus parameter tracking YouTube (&pp, &si, &feature, &utm_* dst).

    https://www.youtube.com/watch?v=8EaL3CgiCAs&pp=ygUP...
    -> https://www.youtube.com/watch?v=8EaL3CgiCAs
    """
    try:
        p = urlparse(url)
        netloc = p.netloc.lower()
        if "youtube.com" not in netloc and "youtu.be" not in netloc:
            return url
        q = parse_qs(p.query, keep_blank_values=True)
        penting = {}
        for k in ("v", "list", "index", "t", "start", "end"):
            if k in q:
                penting[k] = q[k][0]
        if "youtu.be" in netloc:
            vid = p.path.lstrip("/") or penting.get("v", "")
            penting["v"] = vid
            baru = urlunparse(("https", "www.youtube.com", "/watch",
                               "", urlencode(penting), ""))
        else:
            baru = urlunparse((p.scheme, p.netloc, p.path, "",
                               urlencode(penting), ""))
        return baru
    except Exception:
        return url


def parse_progress(line: str):
    """Angka persen dari baris progres yt-dlp; None bila baris lainnya."""
    m = RE_PROG.search(line)
    return float(m.group(1)) if m else None


class Job:
    _seq = 0
    _seq_lock = threading.Lock()

    def __init__(self, query: str, fmt: str = FORMAT_DEFAULT,
                 quality: str = QUALITY_DEFAULT):
        with Job._seq_lock:
            Job._seq += 1
            self.id = Job._seq
        self.query = query.strip()
        self.format = fmt if fmt in FORMAT_VALID else FORMAT_DEFAULT
        self.quality = quality if self._quality_valid(quality) else QUALITY_DEFAULT
        self.status = "pending"  # pending | running | done | error | canceled
        self.percent = None
        self.lines: deque[str] = deque(maxlen=LOG_MAXLEN)
        self.exitcode = None
        self.file = None          # path hasil convert (di folder kerja job)
        self.dir = None           # folder kerja per-job (dibuat di _run)
        self.video_id = None      # id video YouTube (untuk fallback cover)
        self.started = None
        self.ended = None

    def _quality_valid(self, quality: str) -> bool:
        if self.format == "mp4":
            return quality in MP4_RESOLUSI
        return quality in MP3_BITRATE

    def to_dict(self, tail: int = 25) -> dict:
        return {
            "id": self.id,
            "query": self.query,
            "format": self.format,
            "quality": self.quality,
            "status": self.status,
            "percent": self.percent,
            "exitcode": self.exitcode,
            # nama dasar saja (bukan path server) — fetch memakai id job
            "file": os.path.basename(self.file) if self.file else None,
            "lines": list(self.lines)[-tail:],
        }


class JobManager:
    """Worker thread tunggal; antrian FIFO; cancel mematikan proses jalan.

    Folder kerja: env RAVAAMD_WORK (default $TMPDIR/ravaamd). Start membuang
    sisa >1 jam (aman untuk instance kedua yang masih jalan); hasil job menunggu
    di folder masing-masing sampai di-fetch, gagal, atau keluar history.
    """

    def __init__(self, on_state_change=None):
        self.base = (os.environ.get("RAVAAMD_WORK")
                     or os.path.join(tempfile.gettempdir(), "ravaamd"))
        os.makedirs(self.base, exist_ok=True)
        self._buang_sisa_start()
        self.lock = threading.RLock()
        self.queue: list[Job] = []
        self.history: deque[Job] = deque(maxlen=10)
        self.current: Job | None = None
        self.proc: subprocess.Popen | None = None
        self._cancel = False
        self._dirs: dict[int, str] = {}   # id job done → folder kerjanya
        self.on_state_change = on_state_change or (lambda: None)
        threading.Thread(target=self._loop, daemon=True).start()

    def _buang_sisa_start(self) -> None:
        """Sisa folder job lama (>1 jam — sudah pasti bukan milik fetch aktif)
        dibuang supaya server tak pernah disuruh membersihkan manual."""
        batas = time.time() - 3600
        try:
            entri = os.listdir(self.base)
        except OSError:
            return
        for nama in entri:
            p = os.path.join(self.base, nama)
            try:
                if os.path.getmtime(p) < batas:
                    shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) \
                        else os.unlink(p)
            except OSError:
                pass

    # ---- fetch: hasil convert dikirim ke perangkat lalu dihapus ----
    def ambil(self, jid: int) -> str | None:
        """Path absolut mp3 job done yang MENUNGGU dikirim; None bila tak ada."""
        with self.lock:
            job = next((j for j in self.history
                        if j.id == jid and j.status == "done"), None)
        if job and job.file and os.path.isfile(job.file):
            return job.file
        return None

    def selesai_fetch(self, jid: int) -> None:
        """Panggil SETELAH file terkirim penuh ke perangkat — buang foldernya.

        Bila koneksi putus di tengah, pemanggil MENAHAN ini supaya file masih
        ada untuk percobaan ulang (otomatis dibuang oleh purge berikutnya)."""
        with self.lock:
            d = self._dirs.pop(jid, None)
        if d:
            shutil.rmtree(d, ignore_errors=True)

    # ---- API dipanggil handler HTTP ----
    def add(self, query: str, fmt: str = FORMAT_DEFAULT,
            quality: str = QUALITY_DEFAULT) -> Job:
        if fmt not in FORMAT_VALID:
            fmt = FORMAT_DEFAULT
        job = Job(query, fmt=fmt, quality=quality)
        with self.lock:
            self.queue.append(job)
        self.on_state_change()
        return job

    def cancel(self) -> bool:
        with self.lock:
            proc, job = self.proc, self.current
        if not (proc and proc.poll() is None):
            return False
        self._cancel = True
        try:
            proc.terminate()
        except OSError:
            pass
        if job:
            job.lines.append("== canceled by user ==")
        return True

    def state(self) -> dict:
        with self.lock:
            return {
                "current": self.current.to_dict() if self.current else None,
                "queue": [j.to_dict(tail=1) for j in self.queue],
                "history": [j.to_dict(tail=1) for j in self.history],
            }

    # ---- worker ----
    def _loop(self):
        while True:
            job = None
            with self.lock:
                if self.queue:
                    job = self.queue.pop(0)
                    job.status = "running"
                    job.started = time.time()
                    self.current = job
            if job is None:
                time.sleep(0.25)
                continue
            self._run(job)

    def _run(self, job: Job):
        self._cancel = False
        # folder kerja khusus job ini — hasil tak bercampur & mudah dibuang
        job.dir = tempfile.mkdtemp(prefix=f"job-{job.id}-", dir=self.base)
        if FAKE:
            self._run_fake(job)
            self._finish(job)
            return

        hint = None
        kandidat_urls = []
        if job.query.startswith(("http://", "https://")):
            # URL eksplisit: bersihkan parameter tracking YouTube dulu
            url_bersih = bersih_url_youtube(job.query)
            if url_bersih != job.query:
                job.lines.append(f"URL dibersihkan: parameter tracking dihilangkan")
            kandidat_urls.append(url_bersih)
        elif job.format == "mp4":
            # MP4: YouTube dulu (video), fallback YouTube Music
            kandidat_urls.append("ytsearch1:" + job.query)
            hint = cari_ytm(job.query)
            if hint:
                kandidat_urls.append(f"https://www.youtube.com/watch?v={hint['video_id']}")
                job.lines.append(f"YTM: {hint['judul']} — {hint['artis'] or '?'} "
                                 f"({hint['tipe']})")
        else:
            # MP3: YouTube Music dulu (audio), fallback YouTube biasa
            job.lines.append("searching YouTube Music…")
            hint = cari_ytm(job.query)
            if hint:
                kandidat_urls.append(f"https://www.youtube.com/watch?v={hint['video_id']}")
                job.lines.append(f"YTM: {hint['judul']} — {hint['artis'] or '?'} "
                                 f"({hint['tipe']})")
            else:
                job.lines.append("YTM empty → fallback YouTube")
            kandidat_urls.append("ytsearch1:" + job.query)
        code = 1
        for i, url in enumerate(kandidat_urls):
            if self._cancel:
                break  # dibatalkan user — hentikan segera, jangan coba URL berikutnya
            if i > 0:
                job.lines.append("retry via regular YouTube search…")
            job.lines.append("fetching video info (JS challenge) — this can take a while…")
            sebelum = set(os.listdir(job.dir))
            code = self._jalankan_ytdlp(job, url, job.format, job.quality)
            if code == 0:
                break
        job.exitcode = code
        if code == 0:
            # hasil job = yang tidak ada sebelum yt-dlp jalan (folder kini
            # per-job, jadi kandidatnya pasti milik job ini). Deteksi menurut
            # ekstensi format yang diminta (.mp3 atau .mp4).
            ekst = ".mp4" if job.format == "mp4" else ".mp3"
            baru = [f for f in os.listdir(job.dir)
                    if f.lower().endswith(ekst) and f not in sebelum]
            if baru:
                newest = max(baru, key=lambda f: os.path.getmtime(os.path.join(job.dir, f)))
                job.file = os.path.join(job.dir, newest)
            if job.file:
                # MP3 dengan bitrate spesifik → re-encode lewat ffmpeg
                if job.format == "mp3" and job.quality != "best":
                    code = self._reencode_mp3_bitrate(job, job.quality)
                    if code != 0:
                        job.lines.append("bitrate re-encode skipped due to error")
                self._retag_terpisah(job, hint, job.quality)
                job.percent = 100.0
            else:
                job.lines.append("yt-dlp succeeded but output file not found")
        self._finish(job, error=(code != 0 or not job.file))

    def _jalankan_ytdlp(self, job: Job, url: str, fmt: str,
                        quality: str) -> int:
        """Jalankan yt-dlp untuk SATU url; kembalikan exit code (bukan lempar).

        MP3 (resep terkunci, -x dipertahankan):
          -x --audio-format mp3 --audio-quality 0 --embed-metadata
          --embed-thumbnail --no-playlist
          Bitrate spesifik → setelah unduhan, ffmpeg re-encode ke -b:a <bitrate>.

        MP4 (tanpa -x):
          best      → -f best --merge-output-format mp4
          1080p/720p/480p/360p → -f "bestvideo[height<=N]+bestaudio/best[height<=N]"
                              --merge-output-format mp4
        """
        if fmt == "mp4":
            if quality == "best":
                format_opts = ["best"]
            else:
                h = quality.rstrip("p")
                spesifik = (f"bestvideo[height<={h}]+bestaudio/"
                            f"best[height<={h}]")
                format_opts = [spesifik, "best"]
        else:
            # mp3 — resep terkunci, jangan diubah
            format_opts = ["-x --audio-format mp3 --audio-quality 0"]
        code = 1
        for fmt_opt in format_opts:
            if fmt == "mp4":
                cmd = [
                    YT_DLP, "-f", fmt_opt, "--merge-output-format", "mp4",
                    "--embed-metadata", "--embed-thumbnail", "--no-playlist",
                    "--newline",  # tiap update progres = 1 baris (bukan \r) supaya GUI bisa mem-parse
                    "--print", "after_move:VIDEO_ID:%(id)s",  # id video → jaring pengaman cover
                    "-P", job.dir,
                    "-o", "%(title)s.%(ext)s",
                    url,
                ]
            else:
                # mp3 — resep terkunci, jangan diubah
                cmd = [
                    YT_DLP, "-x", "--audio-format", "mp3", "--audio-quality", "0",
                    "--embed-metadata", "--embed-thumbnail", "--no-playlist",
                    "--newline",  # tiap update progres = 1 baris (bukan \r) supaya GUI bisa mem-parse
                    "--print", "after_move:VIDEO_ID:%(id)s",  # id video → jaring pengaman cover
                    "-P", job.dir,
                    "-o", "%(title)s.%(ext)s",
                    url,
                ]
            job.lines.append("$ " + " ".join(cmd))
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, errors="replace", bufsize=1,
                )
            except OSError as e:
                job.lines.append(f"failed to start yt-dlp: {e}")
                return -1
            with self.lock:
                self.proc = proc
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                if line.startswith("VIDEO_ID:"):
                    vid = line[9:].strip()
                    if re.fullmatch(r"[\w-]{11}", vid):
                        job.video_id = vid
                    continue  # baris teknis, jangan tampilkan di log GUI
                job.lines.append(line)
                pct = parse_progress(line)
                if pct is not None:
                    job.percent = pct
            code = proc.wait()
            self.proc = None
            if code == 0:
                break
            if len(format_opts) > 1:
                job.lines.append(f"format {fmt_opt} gagal, coba best…")
        return code

    def _reencode_mp3_bitrate(self, job: Job, bitrate: str) -> int:
        """Re-encode mp3 hasil unduhan ke bitrate target lewat ffmpeg."""
        f = job.file
        if not f or not os.path.isfile(f):
            return -1
        tmp = f + f".{bitrate}.mp3"
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", f, "-vn", "-c:a", "libmp3lame", "-b:a", bitrate,
            "-id3v2_version", "3", tmp,
        ]
        job.lines.append(f"re-encode mp3 to {bitrate}…")
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if p.returncode != 0 or not os.path.isfile(tmp):
                raise RuntimeError(p.stderr.strip()[:200] or "ffmpeg gagal")
            os.replace(tmp, f)
            job.lines.append(f"bitrate {bitrate} applied ✓")
            return 0
        except (OSError, RuntimeError) as e:
            job.lines.append(f"re-encode gagal: {e}")
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return -1

    def _retag_terpisah(self, job: Job, hint: dict | None,
                        quality: str = QUALITY_DEFAULT) -> None:
        """Tulis ulang tag judul/artis TERPISAH setelah unduhan selesai.

        yt-dlp menulis judul mentah 'Artis - Judul (Official ...)' ke tag —
        Amberol menampilkannya jadi satu gumpal. Remux ffmpeg (-c copy,
        sampul ikut, bitrate tidak berubah) hanya mengganti 2 tag ini;
        tag lain tidak ikut hilang karena tidak disebut ulang.

        Cabang per format:
          * mp3:  -map 0:a:0 -map 0:v:0? -f mp3  (ID3, jaring cover fallback)
          * mp4:  -map 0:v:0 -map 0:a:0? -f mp4  (container mp4, skip cover
                  fallback: ada_sampul deteksi stream video utama, bukan cover)
        """
        f = job.file
        if not f or not os.path.isfile(f):
            return
        sekarang_title, sekarang_artist = baca_tag(f)
        raw = os.path.basename(f)
        ekst = os.path.splitext(raw)[1].lower()
        if ekst in (".mp3", ".mp4"):
            raw = raw[: -len(ekst)]
        if hint and hint.get("judul"):
            judul = bersih_judul(hint["judul"],
                                 artis=hint.get("artis") or sekarang_artist)
            artis = hint.get("artis") or sekarang_artist
        else:
            artis, judul = bagi_judul(
                raw,
                artis_hint=(sekarang_artist if sekarang_artist != sekarang_title else ""))
        judul = judul or sekarang_title
        artis = artis or sekarang_artist
        if judul == sekarang_title and artis == sekarang_artist:
            job.lines.append(f"tag OK: title={judul!r} artist={artis!r}")
        else:
            if ekst == ".mp4":
                tmp = f + ".retag.mp4"
                cmd = [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", f, "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                    "-movflags", "+faststart",
                    "-metadata", f"title={judul}",
                    "-metadata", f"artist={artis}",
                    "-f", "mp4", tmp,
                ]
            else:
                tmp = f + ".retag.mp3"
                cmd = [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", f, "-map", "0:a:0", "-map", "0:v:0?", "-c", "copy",
                    "-metadata", f"title={judul}",
                    "-metadata", f"artist={artis}",
                    "-metadata:s:v", "title=Album cover",
                    "-metadata:s:v", "comment=Cover (front)",
                    "-id3v2_version", "3", "-f", "mp3", tmp,
                ]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if p.returncode != 0 or not os.path.isfile(tmp):
                    raise RuntimeError(p.stderr.strip()[:200] or "ffmpeg failed")
                os.replace(tmp, f)
            except (OSError, RuntimeError) as e:
                job.lines.append(f"retag failed: {e}")
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                return
            t2, a2 = baca_tag(f)
            job.lines.append(f"tag OK: title={t2!r} artist={a2!r}")
        # jaring pengaman cover (HANYA mp3): untuk mp4, ada_sampul() akan
        # selalu positif karena stream video utama ikut terdeteksi — jangan
        # pakai sebagai penanda cover.
        if job.format == "mp3" and not ada_sampul(f) and job.video_id:
            job.lines.append(f"cover missing → fetching thumbnail {job.video_id}…")
            jpg = unduh_sampul(job.video_id)
            if jpg:
                self._pasang_sampul(job, f, jpg)
            else:
                job.lines.append("cover unavailable (thumbnail download failed)")

    def _pasang_sampul(self, job: Job, path: str, jpg: bytes) -> None:
        """Sematkan JPEG cover ke mp3 (remux -c copy; tag lain ikut utuh)."""
        tmp_jpg = None
        tmp = path + ".cover.mp3"
        try:
            fd, tmp_jpg = tempfile.mkstemp(suffix=".jpg")
            with os.fdopen(fd, "wb") as fh:
                fh.write(jpg)
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", path, "-i", tmp_jpg,
                "-map", "0:a:0", "-map", "1:v:0", "-c", "copy",
                "-disposition:v:0", "attached_pic",
                "-metadata:s:v", "title=Album cover",
                "-metadata:s:v", "comment=Cover (front)",
                "-id3v2_version", "3", "-f", "mp3", tmp,
            ]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if p.returncode != 0 or not os.path.isfile(tmp):
                raise RuntimeError(p.stderr.strip()[:200] or "ffmpeg gagal")
            os.replace(tmp, path)
            job.lines.append("cover ditambahkan ✓")
        except (OSError, RuntimeError) as e:
            job.lines.append(f"cover gagal dipasang: {e}")
            try:
                os.unlink(tmp)
            except OSError:
                pass
        finally:
            if tmp_jpg:
                try:
                    os.unlink(tmp_jpg)
                except OSError:
                    pass

    def _run_fake(self, job: Job):
        """Mode test: tanpa jaringan — meniru siklus progres lalu menulis file gagus.

        MP3 = ID3 palsu; MP4 = ftyp box palsu (container mp4 valid sekeliling).
        """
        ekst = ".mp4" if job.format == "mp4" else ".mp3"
        out = os.path.join(job.dir, f"uji-unduh-{job.id}{ekst}")
        for pct in (0.0, 40.0, 100.0):
            job.lines.append(f"[download]  {pct}% of    2.00MiB at  3.33MiB/s ETA 00:00")
            job.percent = pct
            time.sleep(0.15)
        if ekst == ".mp4":
            # ftyp box minimal: ukuran + brand mp42 + kompatibel brands
            with open(out, "wb") as f:
                f.write(b"\x00\x00\x00\x20ftypmp42\x00\x00\x00\x00"
                        b"mp42isom" + b"\x00" * 64)
        else:
            with open(out, "wb") as f:
                f.write(b"ID3\x03\x00\x00\x00" + b"\x00" * 64)
        job.file = out

    def _finish(self, job: Job, error: bool = False):
        job.ended = time.time()
        with self.lock:
            if self._cancel:
                job.status = "canceled"
            else:
                job.status = "error" if error else "done"
            self.history.append(job)
            self.current = None
            self.proc = None
            if job.status == "done" and job.file:
                # menunggu dikirim ke perangkat; foldernya dijaga sampai fetch
                self._dirs[job.id] = job.dir
            elif job.dir:
                # gagal/batal: hasil (parsial) langsung dibuang — server tak menyimpan
                shutil.rmtree(job.dir, ignore_errors=True)
            # job yang terdorong keluar history (overflow) → foldernya ikut dibuang
            live = ({j.id for j in self.history} | {j.id for j in self.queue}
                    | ({self.current.id} if self.current else set()))
            for jid in [k for k in self._dirs if k not in live]:
                shutil.rmtree(self._dirs.pop(jid), ignore_errors=True)
        self.on_state_change()
