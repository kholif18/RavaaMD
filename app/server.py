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


def _akhiran(path: str) -> str:
    return os.path.splitext(path)[1].lower()


class Ctx:
    """State bersama yang diisi run.py: JobManager + referensi server."""

    def __init__(self, jobs):
        self.jobs = jobs
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
                return self._bad("akses path terlarang", 403)
            if not os.path.isfile(path):
                return self._bad("file statis tidak ada", 404)
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
                raise ValueError("payload tidak wajar")
            return json.loads(self.rfile.read(n) or b"{}")

        def _shutdown(self) -> None:
            self._json(200, {"ok": True, "pesan": "server dimatikan"})
            t = threading.Thread(target=(ctx.server or self.server).shutdown, daemon=True)
            t.start()

        # ---- GET ----
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            url = parsed.path
            if url == "/api/state":
                return self._json(200, ctx.jobs.state())
            if url == "/api/fetch":
                # kirim hasil convert ke perangkat peminat (lalu job buang folder)
                raw = (urllib.parse.parse_qs(parsed.query).get("id") or [""])[0]
                try:
                    jid = int(raw)
                except ValueError:
                    return self._bad("id job tidak valid")
                path = ctx.jobs.ambil(jid)
                if not path:
                    return self._bad("file tidak ada (sudah terkirim atau belum selesai)",
                                     404)
                nama = os.path.basename(path)
                try:
                    fh = open(path, "rb")
                    ukuran = os.path.getsize(path)
                except OSError:
                    return self._bad("file tidak bisa dibaca", 404)
                with fh:
                    # filename ASCII aman + filename* UTF-8 (nama berspasi/emoji)
                    ascii_nama = nama.encode("ascii", "replace").decode().replace('"', "")
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        "audio/mpeg" if nama.lower().endswith(".mp3")
                        else "application/octet-stream")
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
                # terkirim penuh → server tidak menyimpan hasil convert
                ctx.jobs.selesai_fetch(jid)
                return
            if url.startswith("/api/"):
                return self._bad("endpoint tidak ada", 404)
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
                    return self._bad("query tidak boleh kosong")
                if len(q) > 300:
                    return self._bad("kuerian terlalu panjang (maks 300)")
                job = ctx.jobs.add(q)
                return self._json(201, {"ok": True, "job": job.to_dict(tail=1)})

            if url == "/api/cancel":
                mungkin = ctx.jobs.cancel()
                return self._json(200, {"ok": True, "batal": mungkin})

            if url == "/api/shutdown":
                return self._shutdown()

            return self._bad("endpoint tidak ada", 404)

    return Handler
