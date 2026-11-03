"""Scan folder musik + probe durasi lewat ffprobe (cache per nama+size+mtime)."""
from __future__ import annotations

import json
import os
import subprocess

AKHIRAN = (".mp3", ".m4a", ".opus", ".ogg", ".flac", ".wav")
_cache: dict[str, tuple[int, int, float | None]] = {}


def _durasi(path: str) -> float | None:
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-print_format", "json", path],
            capture_output=True, text=True, timeout=15,
        )
        d = json.loads(p.stdout or "{}")
        return round(float(d["format"]["duration"]))
    except Exception:
        return None


def scan(folder: str) -> list[dict]:
    rows: list[dict] = []
    for fn in sorted(os.listdir(folder)):
        if not fn.lower().endswith(AKHIRAN):
            continue
        path = os.path.join(folder, fn)
        st = os.stat(path)
        kini = (st.st_size, int(st.st_mtime))
        ent = _cache.get(fn)
        if ent is None or ent[:2] != kini:
            ent = (kini[0], kini[1], _durasi(path))
            _cache[fn] = ent
        rows.append({
            "name": fn,
            "size": st.st_size,
            "mtime": kini[1],
            "duration": ent[2],
        })
    return rows
