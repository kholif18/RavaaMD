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
    : job.status === "done" && job.file ? esc(job.file)  // result → file name
    : [pct, waktu(job.started)].filter(Boolean).join(" · ");
  return `<li>
    <span class="item-utama">
      <span class="item-atas">${esc(job.query)}</span>
      <span class="item-bawah">${bawah}</span>
    </span>
    <span class="pil ${esc(job.status)}">${LABEL[job.status] || esc(job.status)}</span>
  </li>`;
}

let state = null;
let tombolJalan = false;
let formatTerpilih = "mp3";  // default MP3
let kualitasTerpilih = "best";  // default best

// Quality options per format
const KUALITAS_OPSI = {
  mp3: ["best", "320k", "256k", "192k", "128k"],
  mp4: ["best", "1080p", "720p", "480p", "360p"],
};

function render() {
  if (!state) return;
  const cur = state.current, queue = state.queue || [], hist = state.history || [];
  const jalan = !!cur && cur.status === "running";

  // status pill di topbar
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
}

/* ---- toast ---- */
function toast(pesan, tipe = "info") {
  const el = document.createElement("div");
  el.className = `toast ${tipe}`;
  el.textContent = pesan;
  $("toasts").appendChild(el);
  window.setTimeout(() => el.remove(), 3600);
}

/* ---- custom confirmation dialog (replaces native confirm()) ---- */
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

/* ---- populate quality dropdown based on selected format ---- */
function muatKualitas() {
  const select = $("kualitas");
  const label = $("kualitas-label");
  const ops = KUALITAS_OPSI[formatTerpilih] || ["best"];
  select.innerHTML = ops.map(v => `<option value="${v}">${v === "best" ? "Best" : v}</option>`).join("");
  // keep current selection if still valid, else reset to best
  if (!ops.includes(kualitasTerpilih)) {
    kualitasTerpilih = "best";
  }
  select.value = kualitasTerpilih;
  label.textContent = formatTerpilih === "mp4" ? "Resolution" : "Bitrate";
}

window.addEventListener("DOMContentLoaded", () => {
  $("form-unduh").addEventListener("submit", (e) => { e.preventDefault(); unduh(); });
  // toggle format MP3/MP4
  $("form-unduh").addEventListener("click", (e) => {
    if (e.target.matches(".fmt-btn")) {
      document.querySelectorAll(".fmt-btn").forEach(b => b.classList.remove("aktif"));
      e.target.classList.add("aktif");
      formatTerpilih = e.target.dataset.fmt;
      kualitasTerpilih = "best";
      muatKualitas();
    }
  });
  // remember quality selection
  $("kualitas").addEventListener("change", (e) => {
    kualitasTerpilih = e.target.value;
  });
  $("btn-cancel").addEventListener("click", () => api("/api/cancel", {}));
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
  tarikSelesai();
}

/* ---- pull converted result to device (done → direct download) ----
   Only the tab that SENT the download request pulls its result:
   sessionStorage survives reload but disappears when tab is closed —
   no surprise downloads from old sessions. Server deletes file only
   after full transfer, so failed attempts can be retried (max 3). */
const K_MINTA = "ytmp3-minta", K_SUDAH = "ytmp3-sudah";
function muatSet(k) {
  try { return new Set(JSON.parse(sessionStorage.getItem(k) || "[]")); } catch { return new Set(); }
}
function simpanSet(k, s) {
  try { sessionStorage.setItem(k, JSON.stringify([...s].slice(-30))); } catch { /* private mode: OK */ }
}
const minta = muatSet(K_MINTA);   // job ids requested by this tab
const sudah = muatSet(K_SUDAH);   // ids already fetched / given up
const sedang = new Set();         // ids being fetched (prevent double across polls)
const coba = {};                  // id → failed attempts

async function tarikHasil(job) {
  const id = job.id;
  sedang.add(id);
  try {
    const res = await fetch("/api/fetch?id=" + id);
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new Error(e.error || "HTTP " + res.status);
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = job.file;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(a.href), 30_000);
    sudah.add(id);
    simpanSet(K_SUDAH, sudah);
    toast(`"${job.file}" saved to Downloads folder`, "sukses");
  } catch (e) {
    coba[id] = (coba[id] || 0) + 1;
    if (coba[id] >= 3) {          // give up — stop spamming retries
      sudah.add(id);
      simpanSet(K_SUDAH, sudah);
      toast(`Failed to fetch "${job.file}": ${e.message}`, "error");
    }
    // < 3 attempts: id not marked → next poll retries
  } finally {
    sedang.delete(id);
  }
}

function tarikSelesai() {
  if (!state) return;
  for (const job of state.history || []) {
    if (job.status !== "done" || !job.file) continue;
    if (!minta.has(job.id) || sudah.has(job.id) || sedang.has(job.id)) continue;
    tarikHasil(job);  // no await — poll keeps running every 800 ms
  }
}

async function unduh() {
  if (tombolJalan) return;
  const q = $("q").value.trim();
  if (!q) { $("q").focus(); return; }
  tombolJalan = true;
  render();
  const r = await api("/api/download", { query: q, format: formatTerpilih, quality: kualitasTerpilih });
  tombolJalan = false;
  if (r.error) toast(r.error, "error");
  else {
    $("q").value = "";
    minta.add(r.job.id);          // this tab is entitled to fetch this job's result
    simpanSet(K_MINTA, minta);
    toast("Added to queue", "sukses");
  }
  render();
}
