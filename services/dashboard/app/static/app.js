/**
 * Media Platform dashboard — overview + Live TV / Guide / Radio / Recordings.
 */
const API = "/api/v1";
const ENT = `${API}/entertainment`;

const el = (id) => document.getElementById(id);

async function fetchJson(path, options = {}) {
  const res = await fetch(path.startsWith("http") || path.startsWith("/api") ? path : `${API}${path}`, {
    headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}) },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${path} → ${res.status} ${text.slice(0, 180)}`);
  }
  const type = res.headers.get("content-type") || "";
  if (type.includes("application/json")) return res.json();
  return res.text();
}

function setStatus(msg, isError = false) {
  const s = el("status");
  s.textContent = msg || "";
  s.classList.toggle("error", !!isError);
}

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatGb(bytes) {
  if (bytes == null || Number.isNaN(Number(bytes))) return "—";
  return `${(Number(bytes) / 1024 ** 3).toFixed(1)} GB`;
}

function badgeClass(status) {
  const s = String(status || "").toLowerCase();
  if (["completed", "ok", "healthy"].includes(s)) return "badge completed";
  if (["failed", "error", "critical"].includes(s)) return "badge failed";
  if (["running", "downloading", "recording", "scheduled"].includes(s)) return "badge running";
  return "badge pending";
}

/* ── Views ─────────────────────────────────────────────── */

function switchView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  const view = el(`view-${name}`);
  if (view) view.classList.add("active");
  if (name === "livetv") loadChannels();
  if (name === "guide") loadGuide();
  if (name === "radio") loadStations();
  if (name === "recordings") loadRecordings();
  if (name === "overview") loadOverview();
}

document.getElementById("main-nav").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab");
  if (!btn) return;
  switchView(btn.dataset.view);
});

/* ── Overview ──────────────────────────────────────────── */

async function loadMovies() {
  const movies = await fetchJson("/movies?limit=12");
  el("movie-count").textContent = String(movies.length >= 12 ? `${movies.length}+` : movies.length);
  const list = el("movie-list");
  list.innerHTML = "";
  if (!movies.length) {
    list.innerHTML = `<li class="muted">No movies yet</li>`;
    return;
  }
  for (const m of movies.slice(0, 10)) {
    const li = document.createElement("li");
    const year = m.year ? ` (${m.year})` : "";
    li.innerHTML = `<span class="movie-title">${escapeHtml(m.title)}${year}</span>`;
    list.appendChild(li);
  }
}

async function loadJobs() {
  const jobs = await fetchJson("/jobs");
  el("job-count").textContent = String(jobs.length);
  const list = el("job-list");
  list.innerHTML = "";
  if (!jobs.length) {
    list.innerHTML = `<li class="muted">No recent jobs</li>`;
    return;
  }
  for (const job of jobs.slice(0, 10)) {
    const li = document.createElement("li");
    li.innerHTML = `
      <span class="job-name">${escapeHtml(job.name || job.id)}</span>
      <span class="${badgeClass(job.status)}">${escapeHtml(job.status || "unknown")}</span>
    `;
    list.appendChild(li);
  }
}

async function loadStorage() {
  const storage = await fetchJson("/storage");
  const free = storage.free_gb != null ? `${storage.free_gb} GB` : formatGb(storage.free_bytes);
  el("storage-free").textContent = free;
}

async function loadHealth() {
  try {
    const health = await fetchJson("/health");
    if (typeof health.open_issues === "number") {
      el("health-issues").textContent = String(health.open_issues);
    } else if (health.status) {
      el("health-issues").textContent = health.status === "healthy" ? "0" : "?";
    }
  } catch {
    el("health-issues").textContent = "—";
  }
}

async function loadOverview() {
  setStatus("Loading overview…");
  try {
    await Promise.all([loadMovies(), loadJobs(), loadStorage(), loadHealth()]);
    setStatus("");
  } catch (err) {
    setStatus(err.message, true);
  }
}

el("refresh")?.addEventListener("click", () => loadOverview());

/* ── Live TV playback ──────────────────────────────────── */

let tvHls = null;

function playTv(channel) {
  const video = el("tv-player");
  const url = channel.play_url || `${ENT}/stream/iptv/${channel.id}`;
  el("tv-now-title").textContent = channel.name;
  const now = channel.now?.title ? `Now: ${channel.now.title}` : "";
  const next = channel.next?.title ? `Next: ${channel.next.title}` : "";
  el("tv-now-meta").textContent = [channel.group_name, now, next].filter(Boolean).join(" · ");

  if (tvHls) {
    tvHls.destroy();
    tvHls = null;
  }

  if (window.Hls && Hls.isSupported() && (url.includes(".m3u8") || true)) {
    // Try HLS first; falls back if not HLS
    tvHls = new Hls({ enableWorker: true });
    tvHls.loadSource(url);
    tvHls.attachMedia(video);
    tvHls.on(Hls.Events.ERROR, () => {
      // Non-HLS upstream — use native
      if (tvHls) {
        tvHls.destroy();
        tvHls = null;
      }
      video.src = url;
      video.play().catch(() => {});
    });
    video.play().catch(() => {});
  } else {
    video.src = url;
    video.play().catch(() => {});
  }
}

async function loadChannels() {
  const group = el("channel-group").value;
  const q = new URLSearchParams({ with_epg: "true" });
  if (group) q.set("group", group);
  setStatus("Loading channels…");
  try {
    const channels = await fetchJson(`${ENT}/iptv/channels?${q}`);
    const grid = el("channel-grid");
    grid.innerHTML = "";
    if (!channels.length) {
      grid.innerHTML = `<p class="muted">No channels yet — import an M3U playlist.</p>`;
      setStatus("");
      return;
    }

    // Populate groups once
    const groupSelect = el("channel-group");
    if (groupSelect.options.length <= 1) {
      try {
        const { groups } = await fetchJson(`${ENT}/iptv/groups`);
        for (const g of groups || []) {
          const opt = document.createElement("option");
          opt.value = g;
          opt.textContent = g;
          groupSelect.appendChild(opt);
        }
      } catch { /* ignore */ }
    }

    for (const ch of channels) {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "channel-card";
      const nowTitle = ch.now?.title ? escapeHtml(ch.now.title) : "No EPG";
      card.innerHTML = `
        <span class="ch-name">${escapeHtml(ch.name)}</span>
        <span class="ch-group">${escapeHtml(ch.group_name || "IPTV")}</span>
        <span class="ch-now">${nowTitle}</span>
        <span class="ch-actions">
          <span class="linkish">Play</span>
          <span class="linkish fav" data-fav="${ch.id}">${ch.is_favorite ? "★" : "☆"}</span>
        </span>
      `;
      card.addEventListener("click", (e) => {
        if (e.target.closest(".fav")) {
          e.stopPropagation();
          toggleChannelFav(ch.id, !ch.is_favorite);
          return;
        }
        playTv(ch);
      });
      grid.appendChild(card);
    }
    setStatus(`${channels.length} channels`);
  } catch (err) {
    setStatus(err.message, true);
  }
}

async function toggleChannelFav(id, favorite) {
  await fetchJson(`${ENT}/iptv/channels/${id}/favorite?favorite=${favorite}`, { method: "POST" });
  loadChannels();
}

el("btn-import-m3u")?.addEventListener("click", async () => {
  const url = el("m3u-url").value.trim();
  if (!url) return setStatus("Enter an M3U URL", true);
  setStatus("Importing playlist…");
  try {
    const result = await fetchJson(`${ENT}/iptv/import`, {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    setStatus(`Imported ${result.created} new, updated ${result.updated}`);
    loadChannels();
  } catch (err) {
    setStatus(err.message, true);
  }
});

el("btn-refresh-channels")?.addEventListener("click", () => loadChannels());
el("channel-group")?.addEventListener("change", () => loadChannels());

/* ── Guide ─────────────────────────────────────────────── */

async function loadGuide() {
  setStatus("Loading guide…");
  try {
    const data = await fetchJson(`${ENT}/epg/guide?hours=6`);
    const list = el("guide-list");
    list.innerHTML = "";
    const channels = data.channels || [];
    const guide = data.guide || {};
    if (!channels.length) {
      list.innerHTML = `<p class="muted">No channels. Import M3U first.</p>`;
      setStatus("");
      return;
    }
    for (const ch of channels.slice(0, 80)) {
      const programs = guide[ch.epg_id] || [];
      const now = programs.find((p) => p.is_now);
      const next = programs.find((p) => !p.is_now);
      const row = document.createElement("div");
      row.className = "guide-row";
      row.innerHTML = `
        <div class="guide-ch">
          <strong>${escapeHtml(ch.name)}</strong>
          <span class="muted">${escapeHtml(ch.group_name || "")}</span>
        </div>
        <div class="guide-prog">
          <div><span class="badge running">NOW</span> ${escapeHtml(now?.title || "—")}</div>
          <div class="muted">Next: ${escapeHtml(next?.title || "—")}</div>
        </div>
        <button type="button" class="btn ghost">Watch</button>
      `;
      row.querySelector("button").addEventListener("click", () => {
        switchView("livetv");
        playTv(ch);
      });
      list.appendChild(row);
    }
    setStatus("");
  } catch (err) {
    setStatus(err.message, true);
  }
}

el("btn-epg-refresh")?.addEventListener("click", async () => {
  const url = el("epg-url").value.trim();
  setStatus("Refreshing EPG…");
  try {
    const body = url ? { url } : {};
    const result = await fetchJson(`${ENT}/epg/refresh`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    setStatus(`EPG loaded: ${result.programs || 0} programmes`);
    loadGuide();
  } catch (err) {
    setStatus(err.message, true);
  }
});

/* ── Radio ─────────────────────────────────────────────── */

function playRadio(station) {
  const audio = el("radio-player");
  audio.src = station.play_url || `${ENT}/stream/radio/${station.id}`;
  el("radio-now-title").textContent = station.name;
  audio.play().catch(() => {});
}

async function loadStations() {
  setStatus("Loading stations…");
  try {
    const stations = await fetchJson(`${ENT}/radio/stations`);
    const list = el("station-list");
    list.innerHTML = "";
    if (!stations.length) {
      list.innerHTML = `<p class="muted">No stations yet — add one above.</p>`;
      setStatus("");
      return;
    }
    for (const s of stations) {
      const row = document.createElement("div");
      row.className = "station-row";
      row.innerHTML = `
        <div>
          <strong>${escapeHtml(s.name)}</strong>
          <div class="muted">${escapeHtml(s.genre || "Radio")}${s.country ? " · " + escapeHtml(s.country) : ""}</div>
        </div>
        <div class="ch-actions">
          <button type="button" class="btn ghost play">Play</button>
          <button type="button" class="btn ghost fav">${s.is_favorite ? "★" : "☆"}</button>
        </div>
      `;
      row.querySelector(".play").addEventListener("click", () => playRadio(s));
      row.querySelector(".fav").addEventListener("click", async () => {
        await fetchJson(`${ENT}/radio/stations/${s.id}/favorite?favorite=${!s.is_favorite}`, { method: "POST" });
        loadStations();
      });
      list.appendChild(row);
    }
    setStatus(`${stations.length} stations`);
  } catch (err) {
    setStatus(err.message, true);
  }
}

el("radio-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = Object.fromEntries(fd.entries());
  try {
    await fetchJson(`${ENT}/radio/stations`, { method: "POST", body: JSON.stringify(payload) });
    e.target.reset();
    loadStations();
    setStatus("Station added");
  } catch (err) {
    setStatus(err.message, true);
  }
});

/* ── Recordings ────────────────────────────────────────── */

async function loadRecordings() {
  try {
    const rows = await fetchJson(`${ENT}/recordings`);
    const list = el("recording-list");
    list.innerHTML = "";
    if (!rows.length) {
      list.innerHTML = `<li class="muted">No recordings scheduled</li>`;
      return;
    }
    for (const r of rows) {
      const li = document.createElement("li");
      li.innerHTML = `
        <span class="job-name">${escapeHtml(r.title)}</span>
        <span class="${badgeClass(r.status)}">${escapeHtml(r.status)}</span>
        <span class="muted">${escapeHtml(r.scheduled_start || "")}</span>
      `;
      list.appendChild(li);
    }
  } catch (err) {
    setStatus(err.message, true);
  }
}

el("recording-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = Object.fromEntries(fd.entries());
  payload.scheduled_start = new Date(payload.scheduled_start).toISOString();
  payload.scheduled_end = new Date(payload.scheduled_end).toISOString();
  try {
    await fetchJson(`${ENT}/recordings`, { method: "POST", body: JSON.stringify(payload) });
    e.target.reset();
    loadRecordings();
    setStatus("Recording scheduled");
  } catch (err) {
    setStatus(err.message, true);
  }
});

/* ── Boot ──────────────────────────────────────────────── */

loadOverview();
