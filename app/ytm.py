"""Pencarian katalog YouTube Music — API InnerTube WEB_REMIX (stdlib urllib).

yt-dlp TIDAK punya `ytmsearch` (diverifikasi 2026-10-26), jadi aplikasi
memanggil endpoint search Music sendiri tanpa dependency tambahan.
Struktur respons: item = musicResponsiveListItemRenderer + watchEndpoint.videoId
+ musicVideoType (ATV = trek resmi katalog, UGC = unggahan biasa).
"""
from __future__ import annotations

import json
import urllib.request

YTM_ENDPOINT = "https://music.youtube.com/youtubei/v1/search?prettyPrint=false"


def _runs_text(flex: dict) -> str:
    """Gabung semua run text dari flexColumn YouTube Music."""
    try:
        return "".join(r.get("text", "") for r in
                       flex["musicResponsiveListItemFlexColumnRenderer"]["text"]["runs"])
    except (KeyError, TypeError):
        return ""


def _telusuri_items(o, out=None):
    """Kumpulkan semua musicResponsiveListItemRenderer dalam struktur respons."""
    if out is None:
        out = []
    if isinstance(o, dict):
        if "musicResponsiveListItemRenderer" in o:
            out.append(o["musicResponsiveListItemRenderer"])
        for v in o.values():
            _telusuri_items(v, out)
    elif isinstance(o, list):
        for v in o:
            _telusuri_items(v, out)
    return out


def cari_ytm(kueri: str, batas: float = 10.0) -> dict | None:
    """Cari trek di katalog YouTube Music (API InnerTube WEB_REMIX).

    Preferensi: item ATV (audio track resmi dari katalog Music) — judul
    dan artisnya sudah murni ("Sugar" / "Maroon 5"); kalau tidak ada ATV,
    pakai item pertama yang punya video. None bila gagal (jaringan/struktur
    berubah) — pemanggil tinggal fallback ke pencarian YouTube biasa.
    """
    if not kueri:
        return None
    body = {"context": {"client": {"clientName": "WEB_REMIX",
                                   "clientVersion": "1.20261026.01.00",
                                   "hl": "id", "gl": "ID"}},
            "query": kueri}
    req = urllib.request.Request(
        YTM_ENDPOINT,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=batas) as r:
            data = json.load(r)
    except (OSError, ValueError):
        return None

    kandidat = None
    for item in _telusuri_items(data):
        cols = item.get("flexColumns") or []
        judul = _runs_text(cols[0]) if cols else ""
        sub = _runs_text(cols[1]) if len(cols) > 1 else ""
        try:
            we = (item["overlay"]["musicItemThumbnailOverlayRenderer"]["content"]
                  ["musicPlayButtonRenderer"]["playNavigationEndpoint"]["watchEndpoint"])
            vid = we.get("videoId")
            tipe = (we.get("watchEndpointMusicSupportedConfigs", {})
                    .get("watchEndpointMusicConfig", {})
                    .get("musicVideoType"))
        except (KeyError, TypeError):
            continue
        if not vid or not judul:
            continue
        bagian = [p.strip() for p in sub.split(" • ")]
        artis = bagian[1] if len(bagian) > 1 and bagian[0] != "Artis" else ""
        hasil = {"video_id": vid, "judul": judul, "artis": artis, "tipe": tipe}
        if tipe == "MUSIC_VIDEO_TYPE_ATV":
            return hasil
        if kandidat is None:
            kandidat = hasil
    return kandidat
