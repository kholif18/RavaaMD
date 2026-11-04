#!/usr/bin/env python3
"""API + job cycle tests for RavaaMD (unittest stdlib, no real YouTube calls —
real downloads tested separately, see AGENTS.md §7).

Run: python3 tests/api-test.py
Starts run.py with env RAVAAMD_FAKE=1 so job cycles run without yt-dlp.
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
FAKE_BYTES_MP3 = b"ID3\x03\x00\x00\x00" + b"\x00" * 64
# ftyp box minimal untuk mp4 palsu (container mp4 valid sekeliling)
FAKE_BYTES_MP4 = b"\x00\x00\x00\x20ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64


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
        cls.tujuan = tempfile.mkdtemp(prefix="ravaamd-tujuan-")  # folder tujuan unduhan
        cls.cfg = tempfile.mkdtemp(prefix="ravaamd-cfg-")  # config isolasi (jangan timpa config user)
        env = {**os.environ, "RAVAAMD_FAKE": "1", "RAVAAMD_WORK": cls.kerja,
               "RAVAAMD_CONFIG_DIR": cls.cfg}
        for attempt in range(3):
            cls.port = _bebas_port()
            cls.proc = subprocess.Popen(
                [sys.executable, os.path.join(ROOT, "run.py"),
                 "--port", str(cls.port), "--no-browser",
                 "--folder", cls.tujuan],
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
        shutil.rmtree(cls.tujuan, ignore_errors=True)
        shutil.rmtree(cls.cfg, ignore_errors=True)

    def test_01_index_html(self):
        status, html, _ = self._html()
        self.assertEqual(status, 200)
        self.assertIn("Download", html)

    def _html(self):
        with urllib.request.urlopen(_url(self.port, "/"), timeout=5) as r:
            return r.status, r.read().decode(), r

    def test_02_state_bentuk(self):
        status, st = _get(self.port, "/api/state")
        self.assertEqual(status, 200)
        for kunci in ("current", "queue", "history", "folder"):
            self.assertIn(kunci, st)
        # folder tujuan = pilihan via --folder (fitur pilihan tempat simpan)
        self.assertEqual(st["folder"], self.tujuan)
        # tidak ada fitur pustaka
        self.assertNotIn("library", st)
        self.assertEqual(st["current"], None)
        self.assertEqual(st["queue"], [])
        self.assertEqual(st["history"], [])

    def test_03_download_kosong_ditolak(self):
        status, r = _post(self.port, "/api/download", {"query": ""})
        self.assertEqual(status, 400)
        self.assertIn("error", r)

    def test_03b_format_tidak_valid_ditolak(self):
        status, r = _post(self.port, "/api/download", {"query": "uji lagu", "format": "mkv"})
        self.assertEqual(status, 400)
        self.assertIn("error", r)
        # default format (mp3) accepted when omitted
        status, r = _post(self.port, "/api/download", {"query": "uji lagu"})
        self.assertEqual(status, 201)
        self.assertEqual(r["job"]["format"], "mp3")
        self.assertEqual(r["job"]["quality"], "best")
        # clean up the job just created (fetch to clear work folder)
        jid = r["job"]["id"]
        for _ in range(60):
            time.sleep(0.2)
            _, st = _get(self.port, "/api/state")
            if st["current"] is None and st["history"]:
                break
        _get_bin(self.port, f"/api/fetch?id={jid}")

    def _tunggu_selesai(self, jid):
        """Tunggu job dengan id jid selesai (maks 10 detik)."""
        for _ in range(50):
            time.sleep(0.2)
            job = self._cari_job(jid)
            if job and job["status"] in ("done", "error", "canceled"):
                return job
        return None

    def test_03c_quality_tidak_valid_ditolak(self):
        # invalid mp3 bitrate
        status, r = _post(self.port, "/api/download", {"query": "uji lagu", "format": "mp3", "quality": "64k"})
        self.assertEqual(status, 400)
        self.assertIn("error", r)
        # invalid mp4 resolution
        status, r = _post(self.port, "/api/download", {"query": "uji video", "format": "mp4", "quality": "4k"})
        self.assertEqual(status, 400)
        self.assertIn("error", r)
        # valid mp3 bitrate accepted
        status, r = _post(self.port, "/api/download", {"query": "uji lagu", "format": "mp3", "quality": "192k"})
        self.assertEqual(status, 201)
        self.assertEqual(r["job"]["quality"], "192k")
        jid = r["job"]["id"]
        job = self._tunggu_selesai(jid)
        self.assertIsNotNone(job, "job mp3 192k tidak selesai")
        self.assertEqual(job["status"], "done")
        _get_bin(self.port, f"/api/fetch?id={jid}")
        # valid mp4 resolution accepted
        status, r = _post(self.port, "/api/download", {"query": "uji video", "format": "mp4", "quality": "720p"})
        self.assertEqual(status, 201)
        self.assertEqual(r["job"]["quality"], "720p")
        jid = r["job"]["id"]
        job = self._tunggu_selesai(jid)
        self.assertIsNotNone(job, "job mp4 720p tidak selesai")
        self.assertEqual(job["status"], "done")
        _get_bin(self.port, f"/api/fetch?id={jid}")

    def test_04_fetch_id_invalid_ditolak(self):
        # traversal lewat nama file mustahil — fetch hanya menerima id job int
        status, body, _ = _get_bin(self.port, "/api/fetch?id=../../etc/passwd")
        self.assertEqual(status, 400)
        self.assertIn("error", body.decode())
        status, body, _ = _get_bin(self.port, "/api/fetch?id=999999")
        self.assertEqual(status, 404)

    def _cari_job(self, jid):
        """Cari job dengan id jid di current atau history."""
        _, st = _get(self.port, "/api/state")
        if st["current"] and st["current"]["id"] == jid:
            return st["current"]
        for j in st.get("history", []):
            if j["id"] == jid:
                return j
        return None

    def test_05_siklus_job_fake_lalu_fetch(self):
        status, r = _post(self.port, "/api/download", {"query": "uji lagu"})
        self.assertEqual(status, 201)
        jid = r["job"]["id"]
        self.assertEqual(r["job"]["format"], "mp3")
        # tunggu job selesai (fake ±0.5 s) + tepat 10 s
        terakhir = None
        for _ in range(100):
            terakhir = self._cari_job(jid)
            if terakhir and terakhir["status"] in ("done", "error", "canceled"):
                break
            time.sleep(0.2)
        self.assertIsNotNone(terakhir, "job tidak kunjung selesai")
        self.assertEqual(terakhir["query"], "uji lagu")
        self.assertEqual(terakhir["status"], "done")
        self.assertTrue(terakhir["file"], "job fake harus mencatat file hasil")
        self.assertNotIn("/", terakhir["file"], "file di state = nama dasar saja")
        # fetch: isi file persis hasil convert + header attachment
        status, body, hdr = _get_bin(self.port, f"/api/fetch?id={jid}")
        self.assertEqual(status, 200)
        self.assertEqual(body, FAKE_BYTES_MP3, "isi yang diterima = isi asli file")
        self.assertIn("attachment", hdr.get("Content-Disposition", ""))
        # hasil PINDAH ke folder tujuan; folder kerja kosong
        time.sleep(0.2)
        self.assertEqual(os.listdir(self.kerja), [],
                         "folder kerja harus kosong setelah fetch")
        simpan = os.path.join(self.tujuan, terakhir["file"])
        self.assertTrue(os.path.isfile(simpan),
                        "file harus tersimpan di folder tujuan")
        # fetch ulang = masih 200 (SALINAN — file user tidak dihapus server)
        status, body2, _ = _get_bin(self.port, f"/api/fetch?id={jid}")
        self.assertEqual(status, 200)
        self.assertEqual(body2, FAKE_BYTES_MP3)

    def test_05b_siklus_job_fake_mp4_lalu_fetch(self):
        status, r = _post(self.port, "/api/download", {"query": "uji video", "format": "mp4"})
        self.assertEqual(status, 201)
        self.assertEqual(r["job"]["format"], "mp4")
        jid = r["job"]["id"]
        terakhir = None
        for _ in range(100):
            terakhir = self._cari_job(jid)
            if terakhir and terakhir["status"] in ("done", "error", "canceled"):
                break
            time.sleep(0.2)
        self.assertIsNotNone(terakhir, "job mp4 tidak kunjung selesai")
        self.assertEqual(terakhir["query"], "uji video")
        self.assertEqual(terakhir["format"], "mp4")
        self.assertEqual(terakhir["status"], "done")
        self.assertTrue(terakhir["file"].endswith(".mp4"), "file harus berakhir .mp4")
        self.assertNotIn("/", terakhir["file"], "file di state = nama dasar saja")
        # fetch: isi = fake mp4 + content-type video/mp4
        status, body, hdr = _get_bin(self.port, f"/api/fetch?id={jid}")
        self.assertEqual(status, 200)
        self.assertEqual(body, FAKE_BYTES_MP4, "isi yang diterima = isi asli file mp4")
        self.assertEqual(hdr.get("Content-Type", ""), "video/mp4")
        self.assertIn("attachment", hdr.get("Content-Disposition", ""))
        time.sleep(0.2)
        self.assertEqual(os.listdir(self.kerja), [],
                         "folder kerja harus kosong setelah fetch")
        self.assertTrue(os.path.isfile(os.path.join(self.tujuan, terakhir["file"])),
                        "file mp4 harus tersimpan di folder tujuan")
        # fetch ulang = masih 200 (salinan — file user tidak dihapus)
        status, _, _ = _get_bin(self.port, f"/api/fetch?id={jid}")
        self.assertEqual(status, 200)

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




    def test_08_folder_pilih(self):
        # path relatif ditolak
        status, r = _post(self.port, "/api/folder", {"folder": "masih/relatif"})
        self.assertEqual(status, 400)
        self.assertIn("error", r)
        # folder yang tidak ada ditolak
        status, r = _post(self.port, "/api/folder",
                          {"folder": "/tmp/ravaamd-tidak-ada-xyz"})
        self.assertEqual(status, 400)
        self.assertIn("error", r)
        # folder valid diterima & langsung terbaca di state
        tujuan2 = tempfile.mkdtemp(prefix="ravaamd-tujuan2-")
        try:
            status, r = _post(self.port, "/api/folder", {"folder": tujuan2})
            self.assertEqual(status, 200)
            self.assertEqual(r["folder"], tujuan2)
            _, st = _get(self.port, "/api/state")
            self.assertEqual(st["folder"], tujuan2)
            # unduhan berikutnya masuk ke folder baru
            status, r = _post(self.port, "/api/download", {"query": "uji lagu"})
            self.assertEqual(status, 201)
            jid = r["job"]["id"]
            job = self._tunggu_selesai(jid)
            self.assertIsNotNone(job, "job tidak selesai")
            self.assertEqual(job["status"], "done")
            self.assertTrue(os.path.isfile(os.path.join(tujuan2, job["file"])),
                            "file harus tersimpan di folder tujuan baru")
        finally:
            _post(self.port, "/api/folder", {"folder": self.tujuan})  # kembalikan
            shutil.rmtree(tujuan2, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
