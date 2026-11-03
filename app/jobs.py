"""Antrian unduhan — eksekusi yt-dlp SATU job sekaligus (urutan memakai lock).

Server = CONVERTER MURNI (keputusan user 2026-11-03): hasil convert tinggal di
folder kerja per-job, dikirim ke perangkat peminat lewat `GET /api/fetch`,
lalu DIHAPUS — tidak ada hasil yang disimpan di server (tak ada pembersihan
manual). Folder kerja dibuang juga saat: start (sisa crash), job gagal/batal,
dan job keluar dari history (overflow).

Invarian yang dijaga (lihat AGENTS.md §5):
  * HANYA satu process yt-dlp jalan bersamaan; job berikutnya menunggu.
  * Selalu `-x --audio-format mp3 --audio-quality 0 --embed-metadata
    --embed-thumbnail --no-playlist` supaya hasilnya punya tag + cover —
    itulah satu-satunya alasan proyek ini ada (Amberol tidak membaca nama file).
  * Argumen URL dipindah lewat argv list (bukan command string), jadi
    judul dengan apostrof/quote/emoji apa pun aman dari shell injection.
  * Gagal = job.status "error" + exitcode; TIDAK PERNAH melempar ke caller.

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

from .tags import (ada_sampul, baca_tag, bagi_judul, bersih_judul,
                   unduh_sampul)
from .ytm import cari_ytm

YT_DLP = os.environ.get("RAVAAMD_YTDLP", os.path.expanduser("~/.local/bin/yt-dlp"))
FAKE = os.environ.get("RAVAAMD_FAKE") == "1"  # dipakai tests/ (tanpa jaringan)

# baris progres yt-dlp: "[download]  42.5% of    4.00MiB at  2.11MiB/s ETA 00:02"
RE_PROG = re.compile(r"(\d+(?:\.\d+)?)% of")
LOG_MAXLEN = 500  # baris nyata disimpan per job (deque)


def parse_progress(line: str):
    """Angka persen dari baris progres yt-dlp; None bila baris lainnya."""
    m = RE_PROG.search(line)
    return float(m.group(1)) if m else None


class Job:
    _seq = 0
    _seq_lock = threading.Lock()

    def __init__(self, query: str):
        with Job._seq_lock:
            Job._seq += 1
            self.id = Job._seq
        self.query = query.strip()
        self.status = "pending"  # pending | running | done | error | canceled
        self.percent = None
        self.lines: deque[str] = deque(maxlen=LOG_MAXLEN)
        self.exitcode = None
        self.file = None          # path mp3 hasil convert (di folder kerja job)
        self.dir = None           # folder kerja per-job (dibuat di _run)
        self.video_id = None      # id video YouTube (untuk fallback cover)
        self.started = None
        self.ended = None

    def to_dict(self, tail: int = 25) -> dict:
        return {
            "id": self.id,
            "query": self.query,
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
    def add(self, query: str) -> Job:
        job = Job(query)
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
            job.lines.append("== dibatalkan user ==")
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
            kandidat_urls.append(job.query)  # URL eksplisit: apa adanya
        else:
            job.lines.append("cari di YouTube Music…")
            hint = cari_ytm(job.query)
            if hint:
                kandidat_urls.append(f"https://www.youtube.com/watch?v={hint['video_id']}")
                job.lines.append(f"YTM: {hint['judul']} — {hint['artis'] or '?'} "
                                 f"({hint['tipe']})")
            else:
                job.lines.append("YTM kosong → fallback YouTube biasa")
            kandidat_urls.append("ytsearch1:" + job.query)  # cadangan / pencarian biasa
        code = 1
        for i, url in enumerate(kandidat_urls):
            if i > 0:
                job.lines.append("coba ulang via pencarian YouTube biasa…")
            sebelum = set(os.listdir(job.dir))
            code = self._jalankan_ytdlp(job, url)
            if code == 0:
                break
        job.exitcode = code
        if code == 0:
            # mp3 hasil job = yang tidak ada sebelum yt-dlp jalan (folder kini
            # per-job, jadi kandidatnya pasti milik job ini)
            baru = [f for f in os.listdir(job.dir)
                    if f.lower().endswith(".mp3") and f not in sebelum]
            if baru:
                newest = max(baru, key=lambda f: os.path.getmtime(os.path.join(job.dir, f)))
                job.file = os.path.join(job.dir, newest)
            if job.file:
                self._retag_terpisah(job, hint)
                job.percent = 100.0
            else:
                job.lines.append("yt-dlp sukses tapi mp3 tidak ditemukan")
        self._finish(job, error=(code != 0 or not job.file))

    def _jalankan_ytdlp(self, job: Job, url: str) -> int:
        """Jalankan yt-dlp untuk SATU url; kembalikan exit code (bukan lempar)."""
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
            job.lines.append(f"tolak jalankan yt-dlp: {e}")
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
        return code

    def _retag_terpisah(self, job: Job, hint: dict | None) -> None:
        """Tulis ulang tag judul/artis TERPISAH setelah unduhan selesai.

        yt-dlp menulis judul mentah 'Artis - Judul (Official ...)' ke tag —
        Amberol menampilkannya jadi satu gumpal. Remux ffmpeg (-c copy,
        sampul APIC ikut, bitrate tidak berubah) hanya mengganti 2 tag ini;
        tag lain tidak ikut hilang karena tidak disebut ulang.
        """
        f = job.file
        if not f or not os.path.isfile(f):
            return
        sekarang_title, sekarang_artist = baca_tag(f)
        raw = os.path.basename(f)
        if raw.lower().endswith(".mp3"):
            raw = raw[:-4]
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
            job.lines.append(f"tag OK: judul={judul!r} artis={artis!r}")
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
                    raise RuntimeError(p.stderr.strip()[:200] or "ffmpeg gagal")
                os.replace(tmp, f)
            except (OSError, RuntimeError) as e:
                job.lines.append(f"retag gagal: {e}")
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                return
            t2, a2 = baca_tag(f)
            job.lines.append(f"tag OK: judul={t2!r} artis={a2!r}")
        # jaring pengaman: cover hilang → tarik thumbnail resmi lalu sematkan
        if not ada_sampul(f) and job.video_id:
            job.lines.append(f"cover tidak ada → tarik thumbnail {job.video_id}…")
            jpg = unduh_sampul(job.video_id)
            if jpg:
                self._pasang_sampul(job, f, jpg)
            else:
                job.lines.append("cover tidak tersedia (unduhan thumbnail gagal)")

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
        """Mode test: tanpa jaringan — meniru siklus progres lalu menulis file gagus."""
        out = os.path.join(job.dir, f"uji-unduh-{job.id}.mp3")
        for pct in (0.0, 40.0, 100.0):
            job.lines.append(f"[download]  {pct}% of    2.00MiB at  3.33MiB/s ETA 00:00")
            job.percent = pct
            time.sleep(0.15)
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
