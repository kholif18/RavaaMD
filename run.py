#!/usr/bin/env python3
"""Pintu masuk ytmp3-gui: HTTP server + buka browser otomatis.

    python3 run.py                     # folder/config: ~/Music/My Musics, port 8637 (+fallback)
    python3 run.py --no-browser        # untuk uji tanpa pop-up browser
    python3 run.py --folder /tmp/x --port 0 --print-port
    python3 run.py --host 0.0.0.0 --no-browser   # dengar di LAN juga (TANPA auth)

Port: default bind 127.0.0.1 saja; --host0.0.0.0 hanya atas permintaan
eksplisit user (akses LAN rumah; lihat AGENTS.md §5). Bila sibuk, coba
+1 s/d +20. Copy server ThreadingHTTPServer.
Config kecil (folder terakhir) disimpan ~/.config/ytmp3-gui/config.json.
"""
from __future__ import annotations

import argparse
import json
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
DEFAULT_FOLDER = os.path.join(os.path.expanduser("~"), "Music", "My Musics")
CFG_DIR = os.path.join(os.path.expanduser("~"), ".config", "ytmp3-gui")
CFG_PATH = os.path.join(CFG_DIR, "config.json")


def muat_folder() -> str:
    try:
        with open(CFG_PATH) as f:
            folder = json.load(f).get("folder")
        if folder and os.path.isdir(folder):
            return folder
    except (OSError, ValueError):
        pass
    return DEFAULT_FOLDER


def simpan_folder(folder: str) -> None:
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(CFG_PATH, "w") as f:
        json.dump({"folder": folder}, f)


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
    ap = argparse.ArgumentParser(description="ytmp3-gui")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--folder", default=None)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address; 0.0.0.0 = izinkan akses LAN (TANPA auth)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--print-port", action="store_true")
    args = ap.parse_args()

    folder = args.folder or muat_folder()
    os.makedirs(folder, exist_ok=True)
    ctx = Ctx(folder=folder, jobs=JobManager(folder), simpan_folder=simpan_folder)

    port = ambil_port(args.port, args.host)
    handler = build_handler(ctx)
    server = ThreadingHTTPServer((args.host, port), handler)
    server.daemon_threads = True
    ctx.server = server
    port_aktif = server.server_address[1]
    if args.host in ("0.0.0.0", "::"):  # banner lengkap: loopback + LAN
        url = f"http://127.0.0.1:{port_aktif}"
        print(f"ytmp3-gui → {url}   (LAN: http://{_ip_lan()}:{port_aktif})"
              f"   (folder: {ctx.folder})", flush=True)
    else:
        url = f"http://{args.host}:{port_aktif}"
        print(f"ytmp3-gui → {url}   (folder: {ctx.folder})", flush=True)
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
        print("ytmp3-gui ditutup.", flush=True)


if __name__ == "__main__":
    main()
