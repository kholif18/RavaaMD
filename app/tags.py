"""Tag MP3: pisah judul/artis, cek & tarik cover (ffprobe/ffmpeg, argv list).

Helper tanpa state antrian — dipakai app/jobs.py setelah unduhan selesai
(retag _terpisah + jaring pengaman cover) dan oleh tests/api-test.py.
Semua subprocess di sini argv list; TIDAK PERNAH lewat shell string.
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request

# ---- pemisahan tag judul/artis (retag hasil unduhan) ----
KATA_JUNK = (
    "official", "music video", "video", "audio", "lyric", "visualizer",
    "visualiser", "mv", "clip officiel", "hd", "4k", "video clip",
)
BRACKET_AKHIR = re.compile(r"\s*[(\[][^()\[\]]*[)\]]\s*$")


def bersih_judul(judul: str, artis: str = "") -> str:
    """Potong bagian promosi di ekor judul ('(Official Music Video)' dll).

    Grup hanya dibuang bila isinya mengandung kata promosi — "(Kygo Remix)"
    atau "(feat. X)" tetap dipertahankan. Bila artis diketahui, potongan
    'Artis - ' di depan ikut dihapus supaya tag judul murni.
    """
    t = (judul or "").strip()
    while True:
        m = BRACKET_AKHIR.search(t)
        if not m:
            break
        isi = m.group(0).lower()
        if any(k in isi for k in KATA_JUNK):
            t = t[: m.start()]
        else:
            break
    t = t.strip(" \t-–—:|")
    if artis:
        t = re.sub(rf"^\s*{re.escape(artis)}\s*[-–—]\s*", "", t, flags=re.IGNORECASE)
    return t.strip() or judul.strip()


def bagi_judul(judul_mentah: str, artis_hint: str = "") -> tuple[str, str]:
    """Pisah 'Artis - Judul (promosi)' menjadi (artis, judul).

    Pemisah: tanda hubung berpalang spasi (' - ', ' – ', ' — ') supaya nama
    bertanda hubung (mis. 'Stand-By') tidak ikut terpecah. Tanpa pemisah,
    artis diisi hint (uploader yang terekam yt-dlp).
    """
    m = re.search(r"\s+[-–—|]\s+", judul_mentah)
    if m:
        artis = judul_mentah[: m.start()].strip()
        judul = bersih_judul(judul_mentah[m.end():], artis_hint or artis)
        return artis or artis_hint, judul
    return artis_hint, bersih_judul(judul_mentah, artis_hint)


def baca_tag(path: str) -> tuple[str, str]:
    """(title, artist) dari file audio via ffprobe; ("", "") bila gagal."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags=title,artist",
             "-of", "json", path],
            capture_output=True, text=True, timeout=30,
        ).stdout
        tags = json.loads(out or "{}").get("format", {}).get("tags", {}) or {}
        return str(tags.get("title", "") or ""), str(tags.get("artist", "") or "")
    except (OSError, ValueError, subprocess.SubprocessError):
        return "", ""


def ada_sampul(path: str) -> bool:
    """True bila file punya stream gambar tertanam (cover APIC)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v",
             "-show_entries", "stream=index", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        ).stdout
        return bool(out.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def unduh_sampul(video_id: str, batas: float = 10.0) -> bytes | None:
    """Bytes JPEG thumbnail video dari i.ytimg.com; None bila gagal.

    Jaring pengaman: `--embed-thumbnail` yt-dlp kadang gagal menyematkan
    (mis. thumbnail 404) — cover ditarik lalu dipasang lewat remux terpisah.
    """
    if not re.fullmatch(r"[\w-]{11}", video_id or ""):
        return None
    for ukuran in ("maxresdefault", "hqdefault", "mqdefault"):
        url = f"https://i.ytimg.com/vi/{video_id}/{ukuran}.jpg"
        try:
            with urllib.request.urlopen(url, timeout=batas) as r:
                data = r.read()
            if len(data) > 1000 and data.startswith(b"\xff\xd8"):
                return data
        except OSError:
            continue
    return None
