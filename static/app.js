/* RavaaMD — UI logic (vanilla, no framework, offline).
   Pattern: poll /api/state every 800 ms → full re-render.
   All listeners attached in DOMContentLoaded — no inline onclick.
   All dynamic text (query/file name) goes through esc() before HTML. */
"use strict";

const $ = (id) => document.getElementById(id);
const waktu = (t) => t ? new Date(t * 1000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }) : "";

const IKON_NOTA = `<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M9 18.5A2.5 2.5 0 1 0 11 16V6.2l7-1.7v9.5A2.5 2.5 0 1 0 16 17.5V6L9 7.7v10.8Z"/></svg>`;

async function api(path, body) {
  const opt = body !== undefined
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  let res;
  try {
    res = await fetch(path, opt);
  } catch {
    return { error: "server unreachable" };
  }
  const data = await res.json().catch(() => ({ error: "response not JSON" }));
  if (!res.ok) return { ...data, error: data.error || `HTTP ${res.status}` };
  return data;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const LABEL = { pending: "queued", running: "running", done: "done", error: "error", canceled: "canceled" };

function liJob(job) {
  const pct = job.percent == null ? "" : `${Math.round(job.percent)}%`;
  const bawah = job.status === "pending" ? "waiting…"
    : job.status === "done" && job.file ? esc(job.file)
    : [pct, waktu(job.started)].filter(Boolean).join(" · ");
  const dlBtn = job.status === "done" && job.file
    ? `<button class="dl-btn" data-id="${job.id}">Download</button>`
    : "";
  return `<li>
    <span class="item-utama">
      <span class="item-atas">${esc(job.query)}</span>
      <span class="item-bawah">${bawah}</span>
    </span>
    ${dlBtn}
    <span class="pil ${esc(job.status)}">${LABEL[job.status] || esc(job.status)}</span>
  </li>`;
}

let state = null;
let tombolJalan = false;
let formatTerpilih = "mp3";

function render() {
  if (!state) return;
  const cur = state.current, queue = state.queue || [], hist = state.history || [];
  const jalan = !!cur && cur.status === "running";

  const pill = $("status-pill");
  pill.className = "pill-status " + (jalan ? "jalan" : "siap");
  pill.innerHTML = `<i></i>${jalan ? "downloading" : "idle"}`;

  $("cur").hidden = !cur;
  $("btn-cancel").hidden = !jalan;
  if (cur) {
    $("cur-query").textContent = cur.query;
    const bar = $("cur-bar");
    if (cur.percent == null) {
      bar.classList.add("indeterminate");
      $("cur-pct").textContent = "…";
    } else {
      bar.classList.remove("indeterminate");
      bar.style.width = cur.percent + "%";
      $("cur-pct").textContent = Math.round(cur.percent) + "%";
    }
    const log = (cur.lines || []).join("\n");
    if ($("cur-log").textContent !== log) {
      $("cur-log").textContent = log;
      $("cur-log").scrollTop = 1e9;
    }
  }

  $("btn-download").disabled = tombolJalan || !!cur || queue.length >= 10;
  $("queue-wrap").hidden = !queue.length;
  $("queue-count").textContent = queue.length;
  $("queue").innerHTML = queue.map(liJob).join("");

  $("sejarah-wrap").hidden = !hist.length;
  $("sejarah").innerHTML = [...hist].reverse().map(liJob).join("");

  // folder tujuan — jangan timpa input saat user sedang mengetik
  if (document.activeElement !== $("folder-input")) {
    $("folder-input").value = state.folder || "";
  }
}

/* ---- toast ---- */
function toast(pesan, tipe = "info") {
  const el = document.createElement("div");
  el.className = `toast ${tipe}`;
  el.textContent = pesan;
  $("toasts").appendChild(el);
  window.setTimeout(() => el.remove(), 3600);
}

/* ---- confirmation dialog ---- */
function konfirmasi({ judul, pesan, ok = "Continue" }) {
  return new Promise((selesai) => {
    const m = $("modal");
    $("modal-judul").textContent = judul;
    $("modal-pesan").textContent = pesan;
    $("modal-ok").textContent = ok;
    m.hidden = false;
    $("modal-ok").focus();
    const tutup = (hasil) => {
      m.hidden = true;
      m.onclick = null;
      $("modal-ok").removeEventListener("click", ya);
      $("modal-batal").removeEventListener("click", tidak);
      document.removeEventListener("keydown", tekanEsc);
      selesai(hasil);
    };
    const ya = () => tutup(true);
    const tidak = () => tutup(false);
    const tekanEsc = (e) => { if (e.key === "Escape") tutup(false); };
    $("modal-ok").addEventListener("click", ya);
    $("modal-batal").addEventListener("click", tidak);
    document.addEventListener("keydown", tekanEsc);
    m.onclick = (e) => { if (e.target === m) tutup(false); };
  });
}

/* ---- shutdown screen ---- */
function layarMati() {
  document.body.innerHTML = `
    <div class="layar-mati">
      <span class="logo">${IKON_NOTA}</span>
      <h2>Application shut down</h2>
      <p>RavaaMD server has stopped — you may close this tab.</p>
    </div>`;
}

window.addEventListener("DOMContentLoaded", () => {
  $("form-unduh").addEventListener("submit", (e) => { e.preventDefault(); unduh(); });
  // format toggle MP3/MP4 — resolution select only shows for MP4
  $("form-unduh").addEventListener("click", (e) => {
    if (e.target.matches(".fmt-btn")) {
      document.querySelectorAll(".fmt-btn").forEach(b => b.classList.remove("aktif"));
      e.target.classList.add("aktif");
      formatTerpilih = e.target.dataset.fmt;
      $("kualitas-wrap").hidden = formatTerpilih !== "mp4";
    }
  });
  $("btn-cancel").addEventListener("click", () => api("/api/cancel", {}));

  // folder tujuan hasil unduhan
  async function simpanFolder() {
    const f = $("folder-input").value.trim();
    const r = await api("/api/folder", { folder: f });
    if (r.error) toast(r.error, "error");
    else {
      toast("Save folder updated", "sukses");
      $("folder-input").value = r.folder;
    }
  }
  $("btn-folder").addEventListener("click", simpanFolder);
  // simpan otomatis saat user selesai mengedit (blur dengan nilai berubah)
  $("folder-input").addEventListener("change", () => {
    if ($("folder-input").value.trim()) simpanFolder();
  });
  // Enter = simpan, bukan submit form (form-unduh memicu unduhan)
  $("folder-input").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); simpanFolder(); }
  });
  $("btn-open").addEventListener("click", async () => {
    const r = await api("/api/open-folder");
    if (r.error) toast(r.error, "error");  // xdg-open tak ada → pesan jelas
  });
  // manual download for completed jobs (delegation — innerHTML replaced each poll)
  $("sejarah").addEventListener("click", (e) => {
    const btn = e.target.closest(".dl-btn");
    if (btn) tarikHasil({ id: Number(btn.dataset.id), file: "" });
  });
  $("queue").addEventListener("click", (e) => {
    const btn = e.target.closest(".dl-btn");
    if (btn) tarikHasil({ id: Number(btn.dataset.id), file: "" });
  });
  $("btn-exit").addEventListener("click", async () => {
    const ok = await konfirmasi({
      judul: "Quit application?",
      pesan: "Running downloads will be stopped. You can reopen the app anytime.",
      ok: "Quit",
    });
    if (!ok) return;
    await api("/api/shutdown", {});
    layarMati();
  });
  poll();
  window.setInterval(poll, 800);
});

async function poll() {
  const r = await api("/api/state");
  if (r.error) return;
  state = r;
  render();
}

/* ---- manual browser copy (tombol Download per job) ----
   Hasil OTOMATIS tersimpan ke folder tujuan pilihan user (fitur save folder)
   — fetch di sini hanya mengambil SALINAN ke browser (mis. dari HP via LAN);
   file tersimpan TIDAK pernah dihapus server. */
const sedang = new Set();  // id job sedang di-fetch (cegah klik dobel)

async function tarikHasil(job) {
  const id = job.id;
  if (sedang.has(id)) return;
  sedang.add(id);
  try {
    const res = await fetch("/api/fetch?id=" + id);
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new Error(e.error || "HTTP " + res.status);
    }
    const blob = await res.blob();
    // cari nama file asli dari state (untuk a.download)
    let nama = job.file;
    if (state) {
      const j = [...(state.history || []), ...(state.queue || []), state.current]
        .find(x => x && x.id === id);
      if (j && j.file) nama = j.file;
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = nama || "ravaamd-download";
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(a.href), 30_000);
    toast(`"${nama}" downloaded`, "sukses");
  } catch (e) {
    toast(`Failed to fetch job #${id}: ${e.message}`, "error");
  } finally {
    sedang.delete(id);
  }
}

async function unduh() {
  if (tombolJalan) return;
  const q = $("q").value.trim();
  if (!q) { $("q").focus(); return; }
  tombolJalan = true;
  render();
  // MP3 → selalu kualitas terbaik (resep terkunci); MP4 → resolusi terpilih
  const quality = formatTerpilih === "mp4" ? $("kualitas").value : "best";
  const r = await api("/api/download", { query: q, format: formatTerpilih, quality });
  tombolJalan = false;
  if (r.error) toast(r.error, "error");
  else {
    $("q").value = "";
    toast("Added to queue", "sukses");
  }
  render();
}
