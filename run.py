#!/usr/bin/env python3
"""Pintu masuk RavaaMD: HTTP server + buka browser otomatis.

    python3 run.py                     # port 8637 (+fallback), buka browser
    python3 run.py --no-browser        # untuk uji tanpa pop-up browser
    python3 run.py --port 0 --print-port
    python3 run.py --host 0.0.0.0 --no-browser   # dengar di LAN juga (TANPA auth)

Server = converter murni (2026-11-03): TANPA folder tujuan / config — hasil
convert tinggal sebentar di folder kerja (env RAVAAMD_WORK), dikirim ke
perangkat peminat lewat /api/fetch, lalu dihapus. Tidak ada fitur pustaka.

Port: default bind 127.0.0.1 saja; --host0.0.0.0 hanya atas permintaan
eksplisit user (akses LAN rumah; lihat AGENTS.md §5). Bila sibuk, coba
+1 s/d +20. Copy server ThreadingHTTPServer.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:  # biar bisa dijalankan dari path mana pun
    sys.path.insert(0, ROOT)

from app.jobs import JobManager          # noqa: E402
from app.server import Ctx, build_handler  # noqa: E402

DEFAULT_PORT = 8637


def ambil_port(basis: int, host: str = "127.0.0.1") -> int:
    """Kembalikan basis, atau pertamakan kosong basis+1..basis+20 (0 = OS pilih)."""
    if basis == 0:
        return 0
    for p in range(basis, basis + 21):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, p))
            except OSError:
                continue
            return p
    raise RuntimeError(f"port {basis}..{basis + 20} semua sibuk")


def _ip_lan() -> str:
    """IP LAN mesin ini untuk banner --host0.0.0.0; fallback hostname."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # UDP connect hanya pilih route — TANPA paket
        return s.getsockname()[0]
    except OSError:
        pass
    finally:
        s.close()
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "IP-SERVER"


def main() -> None:
    ap = argparse.ArgumentParser(description="RavaaMD")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address; 0.0.0.0 = izinkan akses LAN (TANPA auth)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--print-port", action="store_true")
    args = ap.parse_args()

    ctx = Ctx(jobs=JobManager())

    port = ambil_port(args.port, args.host)
    handler = build_handler(ctx)
    server = ThreadingHTTPServer((args.host, port), handler)
    server.daemon_threads = True
    ctx.server = server
    port_aktif = server.server_address[1]
    if args.host in ("0.0.0.0", "::"):  # banner lengkap: loopback + LAN
        url = f"http://127.0.0.1:{port_aktif}"
        print(f"RavaaMD → {url}   (LAN: http://{_ip_lan()}:{port_aktif})",
              flush=True)
    else:
        url = f"http://{args.host}:{port_aktif}"
        print(f"RavaaMD → {url}", flush=True)
    if args.print_port:
        print(f"PORT={server.server_address[1]}", flush=True)
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("RavaaMD ditutup.", flush=True)


if __name__ == "__main__":
    main()
