"""HTTP server stdlib: rut index/static + API JSON. Bind 127.0.0.1 hanya.
Kontrak endpoint EKSAK ada di AGENTS.md §4 — jangan ubah tanpa update.

Kunci implementasi (pelajaran nyata):
  * `subprocess` selalu argv-list — nama file/judul apostrof aman.
  * POST body dikirim JSON; batasuk 10 KB di-enforce sebelum parse.
  * /api/shutdown jalankan server.shutdown() dari thread terpisah,
    karena memanggilnya dari dalam handler = deadlock.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler

AKHIRAN_STATIS = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}
MAKS_BODY = 10_000

FORMAT_VALID = {"mp3", "mp4"}
FORMAT_DEFAULT = "mp3"

MP4_RESOLUSI = {"best", "1080p", "720p", "480p", "360p"}
MP3_BITRATE = {"best", "320k", "256k", "192k", "128k"}
QUALITY_DEFAULT = "best"


def _quality_valid(fmt: str, quality: str) -> bool:
    if fmt == "mp4":
        return quality in MP4_RESOLUSI
    return quality in MP3_BITRATE


def _akhiran(path: str) -> str:
    return os.path.splitext(path)[1].lower()


class Ctx:
    """State bersama yang diisi run.py: folder tujuan + JobManager + config."""

    def __init__(self, folder: str, jobs, simpan_folder=None):
        self.folder = folder          # folder tujuan hasil unduhan (pilihan user)
        self.jobs = jobs
        self.simpan_folder = simpan_folder or (lambda _f: None)
        self.server = None  # diisi run.py setelah bind


def build_handler(ctx: Ctx) -> type:
    STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")

    class Handler(BaseHTTPRequestHandler):
        # ---- util ----
        def log_message(self, fmt, *args):  # senyap: log spam tiap poll 800 ms
            pass

        def _json(self, code: int, obj) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _bad(self, msg: str, code: int = 400) -> None:
            self._json(code, {"error": msg})

        def _statis(self, url: str) -> None:
            rel = "index.html" if url in ("/", "/index.html") else url[len("/static/"):]
            path = os.path.normpath(os.path.join(STATIC_DIR, rel))
            if not path.startswith(STATIC_DIR + os.sep) and path != STATIC_DIR:
                return self._bad("access denied", 403)
            if not os.path.isfile(path):
                return self._bad("static file not found", 404)
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", AKHIRAN_STATIS.get(_akhiran(path), "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAKS_BODY:
                raise ValueError("payload invalid")
            return json.loads(self.rfile.read(n) or b"{}")

        def _shutdown(self) -> None:
            self._json(200, {"ok": True, "message": "server shutting down"})
            t = threading.Thread(target=(ctx.server or self.server).shutdown, daemon=True)
            t.start()

        # ---- GET ----
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            url = parsed.path
            if url == "/api/state":
                st = ctx.jobs.state()
                st["folder"] = ctx.folder
                return self._json(200, st)
            if url == "/api/open-folder":
                # buka folder tujuan di pengelola berkas (argv list, aman)
                try:
                    subprocess.Popen(["xdg-open", ctx.folder])
                except OSError as e:
                    return self._bad(f"cannot open folder: {e}", 500)
                return self._json(200, {"ok": True, "folder": ctx.folder})
            if url == "/api/fetch":
                # kirim SALINAN hasil convert ke perangkat peminat — file di
                # folder tujuan TIDAK dihapus (itu milik user, bukan antrean)
                raw = (urllib.parse.parse_qs(parsed.query).get("id") or [""])[0]
                try:
                    jid = int(raw)
                except ValueError:
                    return self._bad("invalid job id")
                path = ctx.jobs.ambil(jid)
                if not path:
                    return self._bad("file not found (already sent or not yet complete)",
                                     404)
                nama = os.path.basename(path)
                try:
                    fh = open(path, "rb")
                    ukuran = os.path.getsize(path)
                except OSError:
                    return self._bad("file cannot be read", 404)
                with fh:
                    # filename ASCII aman + filename* UTF-8 (nama berspasi/emoji)
                    ascii_nama = nama.encode("ascii", "replace").decode().replace('"', "")
                    self.send_response(200)
                    if nama.lower().endswith(".mp4"):
                        content_type = "video/mp4"
                    elif nama.lower().endswith(".mp3"):
                        content_type = "audio/mpeg"
                    else:
                        content_type = "application/octet-stream"
                    self.send_header("Content-Type", content_type)
                    self.send_header(
                        "Content-Disposition",
                        f"attachment; filename=\"{ascii_nama}\"; "
                        f"filename*=UTF-8''{urllib.parse.quote(nama)}")
                    self.send_header("Content-Length", str(ukuran))
                    self.end_headers()
                    try:
                        shutil.copyfileobj(fh, self.wfile, 1 << 16)
                    except (OSError, ConnectionError):
                        # koneksi putus di tengah: TAHAN file-nya supaya client
                        # boleh coba lagi (pembersihan tetap otomatis, lihat jobs)
                        return
                # terkirim penuh → bersihkan sisa folder kerja (bila masih ada);
                # file tersimpan di folder tujuan tetap utuh
                ctx.jobs.selesai_fetch(jid)
                return
            if url.startswith("/api/"):
                return self._bad("endpoint not found", 404)
            return self._statis(url)

        # ---- POST ----
        def do_POST(self):
            url = urllib.parse.urlparse(self.path).path
            try:
                data = self._body()
            except (ValueError, json.JSONDecodeError) as e:
                return self._bad(f"body tidak valid: {e}", 400)

            if url == "/api/download":
                q = str(data.get("query", "")).strip()
                if not q:
                    return self._bad("query cannot be empty")
                if len(q) > 300:
                    return self._bad("query too long (max 300)")
                fmt = str(data.get("format", FORMAT_DEFAULT)).strip()
                if fmt not in FORMAT_VALID:
                    return self._bad(f"invalid format (choose {', '.join(sorted(FORMAT_VALID))})")
                quality = str(data.get("quality", QUALITY_DEFAULT)).strip()
                if not _quality_valid(fmt, quality):
                    valid = sorted(MP4_RESOLUSI) if fmt == "mp4" else sorted(MP3_BITRATE)
                    return self._bad(f"invalid quality for {fmt} (choose {', '.join(valid)})")
                job = ctx.jobs.add(q, fmt=fmt, quality=quality)
                return self._json(201, {"ok": True, "job": job.to_dict(tail=1)})

            if url == "/api/cancel":
                mungkin = ctx.jobs.cancel()
                return self._json(200, {"ok": True, "batal": mungkin})

            if url == "/api/folder":
                f = str(data.get("folder", "")).strip()
                if not f:
                    return self._bad("folder cannot be empty")
                if not os.path.isabs(f):
                    return self._bad("folder must be an absolute path")
                if not os.path.isdir(f):
                    return self._bad("folder does not exist")
                ctx.folder = f
                ctx.jobs.set_folder(f)  # worker membaca folder dari SINI
                ctx.simpan_folder(f)    # pilihan terakhir → config
                return self._json(200, {"ok": True, "folder": f})

            if url == "/api/shutdown":
                return self._shutdown()

            return self._bad("endpoint tidak ada", 404)

    return Handler
