#!/usr/bin/env python3
"""Uji API + siklus job RavaaMD (unittest stdlib, tanpa jaringan panggilan nyata
YouTube — unduhan NYATA diuji terpisah, lihat AGENTS.md §7).

Jalankan: python3 tests/api-test.py
Menyalakan run.py dengan env RAVAAMD_FAKE=1 supaya siklus job berjalan tanpa yt-dlp.
"""
import json
import os
import shutil
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

# isi file palsu buatan mode FAKE (harus sama dengan app/jobs.py _run_fake)
FAKE_BYTES = b"ID3\x03\x00\x00\x00" + b"\x00" * 64


def _bebas_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _url(port, path):
    return f"http://127.0.0.1:{port}{path}"


def _get(port, path):
    with urllib.request.urlopen(_url(port, path), timeout=5) as r:
        return r.status, json.loads(r.read() or b"{}")


def _get_bin(port, path):
    """GET yang mengembalikan (status, bytes mentah) — untuk /api/fetch."""
    try:
        with urllib.request.urlopen(_url(port, path), timeout=5) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.read(), dict(e.headers)


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
        cls.kerja = tempfile.mkdtemp(prefix="ravaamd-kerja-")  # folder kerja terisolasi
        env = {**os.environ, "RAVAAMD_FAKE": "1", "RAVAAMD_WORK": cls.kerja}
        for attempt in range(3):
            cls.port = _bebas_port()
            cls.proc = subprocess.Popen(
                [sys.executable, os.path.join(ROOT, "run.py"),
                 "--port", str(cls.port), "--no-browser"],
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
        shutil.rmtree(cls.kerja, ignore_errors=True)

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
        for kunci in ("current", "queue", "history"):
            self.assertIn(kunci, st)
        # server converter murni: TANPA folder & pustaka
        self.assertNotIn("folder", st)
        self.assertNotIn("library", st)
        self.assertEqual(st["current"], None)
        self.assertEqual(st["queue"], [])
        self.assertEqual(st["history"], [])

    def test_03_download_kosong_ditolak(self):
        status, r = _post(self.port, "/api/download", {"query": ""})
        self.assertEqual(status, 400)
        self.assertIn("error", r)

    def test_04_fetch_id_invalid_ditolak(self):
        # traversal lewat nama file mustahil — fetch hanya menerima id job int
        status, body, _ = _get_bin(self.port, "/api/fetch?id=../../etc/passwd")
        self.assertEqual(status, 400)
        self.assertIn("error", body.decode())
        status, body, _ = _get_bin(self.port, "/api/fetch?id=999999")
        self.assertEqual(status, 404)

    def test_05_siklus_job_fake_lalu_fetch(self):
        status, r = _post(self.port, "/api/download", {"query": "uji lagu"})
        self.assertEqual(status, 201)
        jid = r["job"]["id"]
        # tunggu job selesai (fake ±0.5 s) + tepat 10 s
        terakhir = None
        for _ in range(60):
            time.sleep(0.2)
            _, st = _get(self.port, "/api/state")
            cur, hist = st["current"], st["history"]
            if cur is None and hist:
                terakhir = hist[0]
                break
        self.assertIsNotNone(terakhir, "job tidak kunjung selesai")
        self.assertEqual(terakhir["id"], jid)
        self.assertEqual(terakhir["status"], "done")
        self.assertTrue(terakhir["file"], "job fake harus mencatat file hasil")
        self.assertNotIn("/", terakhir["file"], "file di state = nama dasar saja")
        # fetch: isi file persis hasil convert + header attachment
        status, body, hdr = _get_bin(self.port, f"/api/fetch?id={jid}")
        self.assertEqual(status, 200)
        self.assertEqual(body, FAKE_BYTES, "isi yang diterima = isi asli file")
        self.assertIn("attachment", hdr.get("Content-Disposition", ""))
        # server tidak menyimpan: setelah terkirim, folder kerja job dibuang
        time.sleep(0.2)
        self.assertEqual(os.listdir(self.kerja), [],
                         "folder kerja harus kosong setelah fetch")
        # fetch ulang = 404 (sudah terkirim & dihapus)
        status, _, _ = _get_bin(self.port, f"/api/fetch?id={jid}")
        self.assertEqual(status, 404)

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




if __name__ == "__main__":
    unittest.main()
