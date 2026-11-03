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


def _akhiran(path: str) -> str:
    return os.path.splitext(path)[1].lower()


class Ctx:
    """State bersama yang diisi run.py: folder aktif + JobManager + simpan config."""

    def __init__(self, folder: str, jobs, simpan_folder=None):
        from app import library
        self.folder = folder
        self.jobs = jobs
        self.library = library
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

        def _state(self) -> dict:
            st = {"folder": ctx.folder}
            st.update(ctx.jobs.state())
            st["library"] = ctx.library.scan(ctx.folder)
            return st

        def _shutdown(self) -> None:
            self._json(200, {"ok": True, "pesan": "server dimatikan"})
            t = threading.Thread(target=(ctx.server or self.server).shutdown, daemon=True)
            t.start()

        # ---- GET ----
        def do_GET(self):
            url = urllib.parse.urlparse(self.path).path
            if url.startswith("/api/"):
                if url == "/api/state":
                    return self._json(200, self._state())
                if url == "/api/open-folder":
                    # container/tanpa desktop: xdg-open tidak ada → JSON anggun,
                    # jangan lempar traceback (koneksi mati di tengah).
                    if shutil.which("xdg-open") is None:
                        return self._json(501, {
                            "error": "xdg-open tidak tersedia di mesin ini "
                                     "(container tanpa desktop)"})
                    try:
                        subprocess.Popen(["xdg-open", ctx.folder])
                    except OSError as e:
                        return self._json(500, {"error": f"gagal buka folder: {e}"})
                    return self._json(200, {"ok": True})
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

            if url == "/api/folder":
                f = str(data.get("folder", "")).strip()
                if not (f.startswith("/") or f.startswith("~")):
                    return self._bad("folder harus absolute path")
                f = os.path.expanduser(f)
                if not os.path.isdir(f):
                    return self._bad("folder tidak ada")
                ctx.folder = f
                ctx.jobs.folder = f  # worker membaca folder DARI SINI saat job mulai
                ctx.simpan_folder(f)
                return self._json(200, {"ok": True, "folder": ctx.folder})

            if url == "/api/remove":
                name = str(data.get("name", ""))
                # guard: HANYA nama dasar (cegah traversal `../`), ekstensi audio sah
                if (os.path.basename(name) != name or name in ("", ".", "..")
                        or os.path.splitext(name)[1].lower() not in ctx.library.AKHIRAN):
                    return self._bad("nama file tidak valid")
                path = os.path.join(ctx.folder, name)
                if not os.path.isfile(path):
                    return self._bad("file tidak ada", 404)
                os.remove(path)
                return self._json(200, {"ok": True, "name": name})

            if url == "/api/shutdown":
                return self._shutdown()

            return self._bad("endpoint tidak ada", 404)

    return Handler
