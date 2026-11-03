/* ytmp3-gui — logika UI (vanilla, tanpa framework, offline).
   Pola: poll /api/state tiap 800 ms → render ulang penuh.
   Semua listener dipasang di DOMContentLoaded — TIDAK ada onclick inline.
   Semua teks dinamis (query/nama file) lewat esc() sebelum masuk HTML. */
"use strict";

const $ = (id) => document.getElementById(id);
const gb = (n) => n >= 1024 ** 3 ? gi(n) : n >= 1024 ** 2
  ? (n / 1048576).toFixed(1) + " MB"
  : (n / 1024).toFixed(0) + " KB";
const gi = (n) => (n / 1073741824).toFixed(2) + " GB";
const durasi = (s) => s == null ? "" : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
const waktu = (t) => t ? new Date(t * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }) : "";

const IKON_NOTA = `<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M9 18.5A2.5 2.5 0 1 0 11 16V6.2l7-1.7v9.5A2.5 2.5 0 1 0 16 17.5V6L9 7.7v10.8Z"/></svg>`;
const IKON_KOSONG = `<svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M9 18.5A2.5 2.5 0 1 0 11 16V6.2l7-1.7v9.5A2.5 2.5 0 1 0 16 17.5V6L9 7.7v10.8Z"/></svg>`;

async function api(path, body) {
  const opt = body !== undefined
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  let res;
  try {
    res = await fetch(path, opt);
  } catch {
    return { error: "server tidak terjangkau" };
  }
  const data = await res.json().catch(() => ({ error: "balasan bukan JSON" }));
  if (!res.ok) return { ...data, error: data.error || `HTTP ${res.status}` };
  return data;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const LABEL = { pending: "antre", running: "jalan", done: "selesai", error: "gagal", canceled: "batal" };

function liJob(job) {
  const pct = job.percent == null ? "" : `${Math.round(job.percent)}%`;
  const bawah = job.status === "pending" ? "menunggu…"
    : [pct, waktu(job.started)].filter(Boolean).join(" · ");
  return `<li>
    <span class="item-utama">
      <span class="item-atas">${esc(job.query)}</span>
      <span class="item-bawah">${bawah}</span>
    </span>
    <span class="pil ${esc(job.status)}">${LABEL[job.status] || esc(job.status)}</span>
  </li>`;
}

function barisPustaka(r) {
  return `<li>
    <span class="lib-ikon" aria-hidden="true">${IKON_NOTA}</span>
    <span class="item-utama">
      <span class="item-atas">${esc(r.name)}</span>
      <span class="item-bawah">${durasi(r.duration)} · ${gb(r.size)}</span>
    </span>
    <button class="tombol-hapus" data-hapus="${esc(r.name)}"
      title="Hapus file ini dari disk" aria-label="Hapus ${esc(r.name)}">
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
        stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M10 11v6m4-6v6"/>
      </svg>
    </button>
  </li>`;
}

let state = null;
let tombolJalan = false;

function render() {
  if (!state) return;
  const cur = state.current, queue = state.queue || [], hist = state.history || [];
  const jalan = !!cur && cur.status === "running";

  // status pill di topbar
  const pill = $("status-pill");
  pill.className = "pill-status " + (jalan ? "jalan" : "siap");
  pill.innerHTML = `<i></i>${jalan ? "mengunduh" : "siap"}`;

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

  // pustaka
  const lib = state.library || [];
  $("lib-count").textContent = lib.length;
  $("lib").innerHTML = lib.length
    ? lib.map(barisPustaka).join("")
    : `<li class="kosong">${IKON_KOSONG}<b>Belum ada lagu</b>
        <span>Unduh lagu pertamamu — langsung muncul di sini</span></li>`;

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

/* ---- dialog konfirmasi kustom (pengganti confirm() bawaan) ---- */
function konfirmasi({ judul, pesan, ok = "Lanjut" }) {
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

/* ---- layar penutup setelah shutdown ---- */
function layarMati() {
  document.body.innerHTML = `
    <div class="layar-mati">
      <span class="logo">${IKON_NOTA}</span>
      <h2>Aplikasi dimatikan</h2>
      <p>Server ytmp3-gui sudah berhenti — boleh tutup tab ini.</p>
    </div>`;
}

window.addEventListener("DOMContentLoaded", () => {
  $("form-unduh").addEventListener("submit", (e) => { e.preventDefault(); unduh(); });
  $("btn-cancel").addEventListener("click", () => api("/api/cancel", {}));
  $("btn-exit").addEventListener("click", async () => {
    const ok = await konfirmasi({
      judul: "Matikan aplikasi?",
      pesan: "Unduhan yang sedang berjalan akan berhenti. Kamu bisa membukanya kembali kapan saja.",
      ok: "Matikan",
    });
    if (!ok) return;
    await api("/api/shutdown", {});
    layarMati();
  });
  $("btn-open").addEventListener("click", async () => {
    const r = await api("/api/open-folder");
    if (r.error) toast(r.error, "galat");  // container tanpa xdg-open → pesan jelas
  });
  $("btn-folder").addEventListener("click", async () => {
    const f = $("folder-input").value.trim();
    const r = await api("/api/folder", { folder: f });
    if (r.error) toast(r.error, "galat");
    else toast("Folder disimpan", "sukses");
  });
  $("lib").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-hapus]");
    if (!btn) return;
    const nama = btn.dataset.hapus;
    const ok = await konfirmasi({ judul: "Hapus lagu ini?", pesan: nama, ok: "Hapus" });
    if (!ok) return;
    const r = await api("/api/remove", { name: nama });
    if (r.error) toast(r.error, "galat");
    else toast(`"${nama}" dihapus dari disk`, "sukses");
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

async function unduh() {
  if (tombolJalan) return;
  const q = $("q").value.trim();
  if (!q) { $("q").focus(); return; }
  tombolJalan = true;
  render();
  const r = await api("/api/download", { query: q });
  tombolJalan = false;
  if (r.error) toast(r.error, "galat");
  else {
    $("q").value = "";
    toast("Masuk antrian", "sukses");
  }
  render();
}
