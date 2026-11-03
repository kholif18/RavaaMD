#!/usr/bin/env python3
"""Uji API + siklus job ytmp3-gui (unittest stdlib, tanpa jaringan panggilan nyata
YouTube — unduhan NYATA diuji terpisah, lihat AGENTS.md §5).

Jalankan: python3 tests/api-test.py
Menyalakan run.py dengan env YTMP3GUI_FAKE=1 supaya siklus job berjalan tanpa yt-dlp.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.jobs import parse_progress  # noqa: E402


def _bebas_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _url(port, path):
    return f"http://127.0.0.1:{port}{path}"


def _get(port, path):
    with urllib.request.urlopen(_url(port, path), timeout=5) as r:
        return r.status, json.loads(r.read() or b"{}")


def _post(port, path, data):
    req = urllib.request.Request(
        _url(port, path),
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        with e:
            return e.code, json.loads(e.read() or b"{}")


class TestApi(unittest.TestCase):
    port: int
    proc: subprocess.Popen
    folder: str

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix="ytmp3gui-uji-")
        cls.thumb_root = tempfile.mkdtemp(prefix="ytmp3gui-tc-")
        env = {**os.environ, "YTMP3GUI_FAKE": "1",
               "YTMP3GUI_THUMB_CACHE": cls.thumb_root}
        for attempt in range(3):
            cls.port = _bebas_port()
            cls.proc = subprocess.Popen(
                [sys.executable, os.path.join(ROOT, "run.py"),
                 "--port", str(cls.port), "--no-browser", "--folder", cls.folder],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            for _ in range(50):
                try:
                    status, st = _get(cls.port, "/api/state")
                    if status == 200:
                        break
                except Exception:
                    time.sleep(0.1)
            else:
                continue
            return
        raise RuntimeError("server tes tidak bisa dijalankan")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        for f in os.listdir(cls.folder):
            os.remove(os.path.join(cls.folder, f))
        os.rmdir(cls.folder)
        import shutil
        shutil.rmtree(cls.thumb_root, ignore_errors=True)

    def test_01_index_html(self):
        status, html, _ = self._html()
        self.assertEqual(status, 200)
        self.assertIn("Unduh", html)

    def _html(self):
        with urllib.request.urlopen(_url(self.port, "/"), timeout=5) as r:
            return r.status, r.read().decode(), r

    def test_02_state_bentuk(self):
        status, st = _get(self.port, "/api/state")
        self.assertEqual(status, 200)
        for kunci in ("folder", "current", "queue", "history", "library"):
            self.assertIn(kunci, st)
        self.assertEqual(st["folder"], self.folder)
        self.assertEqual(st["current"], None)
        self.assertEqual(st["library"], [])

    def test_03_download_kosong_ditolak(self):
        status, r = _post(self.port, "/api/download", {"query": ""})
        self.assertEqual(status, 400)
        self.assertIn("error", r)

    def test_04_download_serangan_traversal_remove(self):
        status, r = _post(self.port, "/api/remove", {"name": "../../etc/passwd"})
        self.assertEqual(status, 400)

    def test_05_siklus_job_fake(self):
        status, r = _post(self.port, "/api/download", {"query": "uji lagu"})
        self.assertEqual(status, 201)
        jid = r["job"]["id"]
        # tunggu job selesai (fake ±0.5 s) + tepat 10 s
        terakhir = None
        for _ in range(60):
            time.sleep(0.2)
            _, st = _get(self.port, "/api/state")
            cur, hist, lib = st["current"], st["history"], st["library"]
            if cur is None and hist:
                terakhir = hist[0]
                break
        self.assertIsNotNone(terakhir, "job tidak kunjung selesai")
        self.assertEqual(terakhir["id"], jid)
        self.assertEqual(terakhir["status"], "done")
        self.assertTrue(terakhir["file"], "job fake harus mencatat file hasil")
        # pustaka ikut memuatnya setelah selesai (scan otomatis)
        _, st = _get(self.port, "/api/state")
        self.assertTrue(st["library"], "pustaka harus memuat file hasil fake job")

    def test_06_parse_progress(self):
        self.assertEqual(parse_progress("[download]  42.5% of    4.00MiB at  2.11MiB/s ETA 00:01"), 42.5)
        self.assertEqual(parse_progress("[download] 100% of     3.00MiB"), 100.0)
        self.assertIsNone(parse_progress("[ExtractAudio] Destination: x.mp3"))
        self.assertIsNone(parse_progress("hello world"))

    def test_07_bagijudul(self):
        from app.tags import bagi_judul, bersih_judul
        # judul YouTube bergumpal → artis + judul murni, label promosi dibuang
        self.assertEqual(bagi_judul("Maroon 5 - Sugar (Official Music Video)"),
                         ("Maroon 5", "Sugar"))
        self.assertEqual(bagi_judul("DENNY CAKNAN - NEGORO ANGIN (Official Music Video)"),
                         ("DENNY CAKNAN", "NEGORO ANGIN"))
        # label musik yang BUKAN promosi tetap dipertahankan
        self.assertEqual(bagi_judul("Starboy (Kygo Remix)", artis_hint="The Weeknd"),
                         ("The Weeknd", "Starboy (Kygo Remix)"))
        # tanpa pemisah: judul bersih, artis dari hint
        self.assertEqual(bagi_judul("Sugar", artis_hint="Maroon 5"),
                         ("Maroon 5", "Sugar"))
        # judul dengan pemisah spasi-titik-koma dan tanda hubung pada nama
        self.assertEqual(bersih_judul("Sugar (Official Audio)"), "Sugar")
        self.assertEqual(bersih_judul("Sugar (Lyric Video)"), "Sugar")
        self.assertEqual(bersih_judul("Keane - Somewhere Only We Know", "Keane"),
                         "Somewhere Only We Know")

    def test_08_failcache_thumbnail_dibersihkan(self):
        import struct
        from app.thumbs import bersihkan_cache_gagal
        os.environ["YTMP3GUI_THUMB_CACHE"] = self.thumb_root
        try:
            fail_dir = os.path.join(self.thumb_root, "fail", "gnome-thumbnail-factory")
            os.makedirs(fail_dir, exist_ok=True)

            def png(uri: bytes) -> bytes:
                def chunk(t, payload):
                    return (struct.pack(">I", len(payload)) + t + payload
                            + b"\x00\x00\x00\x00")  # CRC boleh nol — parser tak memeriksanya
                return (b"\x89PNG\r\n\x1a\n"
                        + chunk(b"IHDR", b"\x00" * 13)
                        + chunk(b"tEXt", b"Thumb::URI\x00" + uri)
                        + chunk(b"IEND", b""))

            sesudah = "file:///tmp/uji-ytmp3/sesudah.mp3"   # cocok folder uji
            sebelum = "file:///home/enma/Music/My%20Musics/lama.mp3"  # bukan folder uji
            with open(os.path.join(fail_dir, "sesudah.png"), "wb") as f:
                f.write(png(sesudah.encode()))
            with open(os.path.join(fail_dir, "lama.png"), "wb") as f:
                f.write(png(sebelum.encode()))
            n = bersihkan_cache_gagal("/tmp/uji-ytmp3")
            self.assertEqual(n, 1)
            self.assertFalse(os.path.exists(os.path.join(fail_dir, "sesudah.png")))
            self.assertTrue(os.path.exists(os.path.join(fail_dir, "lama.png")))
            # tidak ada entri yang cocok → 0
            self.assertEqual(bersihkan_cache_gagal("/tmp/tidak-ada"), 0)
        finally:
            os.environ.pop("YTMP3GUI_THUMB_CACHE", None)


if __name__ == "__main__":
    unittest.main()
