# ytmp3-gui — image container (docker/Podman; teruji dengan docker 29.x).
# Isi: python3 (stdlib saja — TANPA pip), ffmpeg, node (runtime JS yt-dlp),
# yt-dlp terbaru. Tidak ada langkah pip/npm — resep proyek tetap offline-friendly.
FROM python:3.14-slim

# nodejs WAJIB: tanpa `--js-runtimes node` ekstraksi YouTube 2026 gagal
# (lihat AGENTS.md §2). ffmpeg = -x + embed metadata/thumbnail + ffprobe.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg nodejs ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp di lokasi yang DIBACA default run.py (~/.local/bin/yt-dlp).
# Aset zipapp "yt-dlp" = lintas arsitektur (butuh python3, sudah ada di image).
# Config `--js-runtimes node` dibakar di sini supaya perilaku identik dengan
# mesin user (jangan hapus — lihat AGENTS.md §2).
ARG YT_DLP_URL=https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp
RUN mkdir -p /root/.local/bin /root/.config/yt-dlp \
    && curl -fsSL -o /root/.local/bin/yt-dlp "$YT_DLP_URL" \
    && chmod +x /root/.local/bin/yt-dlp \
    && printf '%s\n' '--js-runtimes node' > /root/.config/yt-dlp/config \
    && /root/.local/bin/yt-dlp --version \
    && node --version

WORKDIR /opt/ytmp3-gui
COPY run.py ./
COPY app ./app
COPY static ./static
COPY tests ./tests

# Build gate: suite tes hijau = image layak pakai (mode FAKE, tanpa jaringan)
RUN python3 tests/api-test.py

ENV PYTHONUNBUFFERED=1
EXPOSE 8637

# Server SELALU bind 127.0.0.1 di dalam container (AGENTS §5); dengan
# network_mode: host (compose) app melayani loopback mesin — tunnel kamu
# menunjuk http://127.0.0.1:8637. Healthcheck scan rentang fallback 8637..8657
# karena run.py boleh pindah port bila 8637 sibuk (mis. GUI native ikut jalan).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD for p in $(seq 8637 8657); do curl -fsS -m 2 "http://127.0.0.1:$p/api/state" >/dev/null 2>&1 && exit 0; done; exit 1

ENTRYPOINT ["python3", "run.py"]
# Folder musik = volume /music (lihat compose.yaml). --no-browser wajib (headless).
CMD ["--folder", "/music", "--no-browser"]
