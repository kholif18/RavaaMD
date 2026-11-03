"""Fail-cache thumbnail GNOME — sumber ikon default di Files.

GNOME hanya men-thumbnail berkas SATU kali: bila usaha pertama gagal
(terjadi persis saat yt-dlp selesai menulis file), status "gagal" ter-cache di
~/.cache/thumbnails/fail/ dan TIDAK PERNAH dicoba ulang selama mtime file
tidak berubah — MP3 tampil sebagai ikon musik default walau sampulnya
tertanam benar. Modul ini membuang entri cadangan fail itu (identifikasi via
chunk PNG `Thumb::URI`) supaya Files men-thumbnail ulang. Berkas musik tidak
disentuh. Akar cache bisa dialihkan env YTMP3GUI_THUMB_CACHE (tests/).
"""
from __future__ import annotations

import os
import urllib.parse


def _thumb_root() -> str:
    """Akar cache thumbnail GNOME; bisa diarahkan ke folder lain untuk uji."""
    env = os.environ.get("YTMP3GUI_THUMB_CACHE")
    return env or os.path.join(os.path.expanduser("~"), ".cache", "thumbnails")


def _thumbnail_uri_png(path: str) -> bytes | None:
    """Nilai chunk tEXt `Thumb::URI` dari PNG cache; None bila tidak ada/rusak."""
    try:
        with open(path, "rb") as f:
            blob = f.read(64 * 1024)
    except OSError:
        return None
    if not blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    i = 8
    while i + 12 <= len(blob):
        ln = int.from_bytes(blob[i:i + 4], "big")
        typ = blob[i + 4:i + 8]
        if typ == b"tEXt":
            k, _, v = blob[i + 8:i + 8 + ln].partition(b"\x00")
            if k == b"Thumb::URI":
                return v
        if i + 12 + ln > len(blob):
            return None
        i += 12 + ln
    return None


def bersihkan_cache_gagal(folder: str) -> int:
    """Hapus entri fail-thumbnail GNOME untuk berkas di dalam `folder`.

    Hanya menyentuh fail-cache milik GNOME; berkas musik tidak diubah.
    Folder cache yang tidak ada (mis. container tanpa GNOME) → 0, bukan error.
    """
    pfail = os.path.join(_thumb_root(), "fail")
    prefix = ("file://" + urllib.parse.quote(folder, safe="/") + "/").encode()
    n = 0
    for kek, _dirs, files in os.walk(pfail):
        for nama in files:
            if not nama.endswith(".png"):
                continue
            p = os.path.join(kek, nama)
            uri = _thumbnail_uri_png(p)
            if uri is not None and uri.startswith(prefix):
                try:
                    os.unlink(p)
                except OSError:
                    continue
                n += 1
    return n
