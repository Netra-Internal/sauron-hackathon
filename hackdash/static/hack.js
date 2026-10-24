// Send drone: the Sites monitor's layout around one addition. Right: camera tiles. Centre: the opened camera, live
// (~1 fps ring frame + the edge person boxes taken at the same instant), each box with a chip `#id conf · suspicion|—`
// and a Send drone button (inline confirm of the operator's own click; Sauron's autonomous launches have no gate).
// Left: the incidents this demo launched (state, location, forwarded/delivered, what the drone received) + Abort.
// Everything is polled from the real APIs under /hack/api; when a piece is missing the page says so and shows nothing.
const API = "/hack/api";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const h = html => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const toast = msg => { const t = h(`<div class="toast">${esc(msg)}</div>`); $("#toasts").append(t); setTimeout(() => t.remove(), 6000); };
const fx = (v, d = 1) => v == null ? "–" : Number(v).toFixed(d);
const ll = (lat, lon) => `${Number(lat).toFixed(6)}, ${Number(lon).toFixed(6)}`;
const cap1 = s => s ? s[0].toUpperCase() + s.slice(1) : s;
const ago = iso => {
  if (!iso) return "";
  const s = Math.round((Date.now() - new Date(iso)) / 1e3);
  return s < 5 ? "just now" : s < 90 ? `${s} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(iso).toLocaleString();
};
const shortId = tu => `#${String(tu || "").replace(/-/g, "").slice(0, 4)}`;
function btn(text, cls, fn, disabled) { const b = h(`<button type="button" class="btn ${cls}">${esc(text)}</button>`); b.onclick = fn; b.disabled = !!disabled; return b; }

async function api(path, opts = {}) {
  const r = await fetch(API + path, { credentials: "same-origin", ...opts, headers: { "Content-Type": "application/json" } });
  if (r.status === 401) { location.href = "/map/login?next=/hack/"; throw Object.assign(new Error("auth"), { status: 401 }); }
  if (!r.ok) { let m = `${r.status}`; try { m = (await r.json()).detail || m; } catch {} throw Object.assign(new Error(m), { status: r.status }); }
  return r.status === 204 ? null : r.json();
}
const post = (path, body) => api(path, { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body || {}) });
// t_ns (~1.8e18) doesn't fit a JS number exactly, and launch matches the clicked obs on the exact t: keep it as the
// digit string from the raw JSON and write it back unquoted
const rawTns = text => text.match(/"t_ns"\s*:\s*(\d+)/)?.[1];

const S = {
  cams: null, camErr: null, cam: null,            // camera list, its error, the open camera id
  gen: 0, live: null, liveErr: null, liveAt: 0,   // live loop generation, the payload on screen, its error
  inc: new Map(), incErr: null, incLoaded: false, sel: null,
  msgs: [], msgSince: 0, msgErr: null,
  pending: new Map(),                             // track_uuid -> {state: "confirm"|"sending", box, t_ns}
  sentByTrack: new Map(),                         // track_uuid -> incident id (launched from this page)
  chips: new Map(),                               // track_uuid -> chip element
};

// ------------------------------------------------------------------ cameras (right)
async function pollCams() {
  try {
    const r = await api("/cameras");
    S.cams = Array.isArray(r) ? r : r.cameras || []; S.camErr = null;
    if (!S.cam) {
      const want = new URLSearchParams(location.hash.slice(1)).get("cam");
      const pick = S.cams.find(c => c.camera_id === want) || (S.cams.filter(c => c.live).length === 1 ? S.cams.find(c => c.live) : null);
      if (pick) openCamera(pick.camera_id);
    }
  } catch (err) { if (err.status !== 401) S.camErr = err.status === 404 ? "The live-view API (hackdash.live) isn't deployed yet." : `Couldn't load cameras: ${err.message}`; }
  renderWall(); renderTop(); renderStage();
}
const camOf = id => S.cams?.find(c => c.camera_id === id);
function renderWall() {
  const wall = $("#wall");
  // only cameras with a current picture: a camera that isn't live (or whose picture won't load) isn't listed
  const cams = (S.cams || []).filter(c => c.live);
  const none = () => h(`<div class="wempty">No camera is live right now.</div>`);
  wall.innerHTML = "";
  wall.append(h(`<div class="whead"><h2>Cameras</h2><span class="muted small">${S.cams ? `${cams.length} live` : ""}</span></div>`));
  if (S.camErr || !cams.length) {
    wall.append(S.camErr || S.cams ? (S.camErr ? h(`<div class="wempty">${esc(S.camErr)}</div>`) : none()) : h(`<div class="wempty">Loading…</div>`));
    return;
  }
  for (const c of cams) {
    const open = S.cam === c.camera_id;
    // the edge preview netra-ask already serves (~30 s old); the open camera falls back to its newest live frame
    const src = `/ask/api/preview/${encodeURIComponent(c.camera_id)}.jpg?m=${Math.floor(Date.now() / 30e3)}`;
    const t = h(`<button class="tile ${open ? "sel" : ""}"><div class="tframe"><img alt="">
      <div class="tover"><i class="live"></i><span>${esc(c.name || c.camera_id)}</span></div></div>
      <div class="tinfo"><div class="tstate">Live${c.fps != null ? ` · ${fx(c.fps, 1)} fps` : ""}${open ? " · open" : ""}</div>
      <div class="tchips">${c.test_rig ? `<span class="chip test">test rig</span>` : ""}${c.calibrated ? `<span class="chip">On the map</span>` : `<span class="chip amber">Not calibrated</span>`}</div></div></button>`);
    const img = t.querySelector("img");
    img.onerror = () => {
      if (open && S.live?.frame_url && !img.dataset.fb) { img.dataset.fb = 1; img.src = frameUrl(S.live.frame_url); return; }
      t.remove(); if (!wall.querySelector(".tile")) wall.append(none());
    };
    img.src = src;
    t.onclick = () => openCamera(c.camera_id);
    wall.append(t);
  }
}

// ------------------------------------------------------------------ the open camera, live (centre)
function openCamera(id) {
  if (S.cam === id) return;
  S.cam = id; S.live = null; S.liveErr = null; S.gen++; S.pending.clear();
  S.chips.forEach(el => el.remove()); S.chips.clear();
  history.replaceState(null, "", `#cam=${encodeURIComponent(id)}`);
  $("#frameinner").classList.add("hidden");
  renderWall(); renderStage();
  liveTick(S.gen);
}
const frameUrl = u => /^(https?:)?\//.test(u) ? u : `${API}/${u}`;
async function liveTick(gen) {
  if (gen !== S.gen) return;
  const t0 = performance.now();
  try {
    const res = await fetch(`${API}/cameras/${encodeURIComponent(S.cam)}/live`, { credentials: "same-origin" });
    if (res.status === 401) { location.href = "/map/login?next=/hack/"; return; }
    const text = await res.text();
    if (!res.ok) { let m = `${res.status}`; try { m = JSON.parse(text).detail || m; } catch {} throw Object.assign(new Error(m), { status: res.status }); }
    const r = JSON.parse(text);
    r.t_ns = rawTns(text) || String(r.t_ns);
    if (gen !== S.gen) return;
    if (r.frame_url) {
      // show the frame and its boxes together: preload the JPEG, then swap it in and draw the payload it belongs to
      const img = new Image();
      img.alt = "Live camera frame";
      await new Promise((ok, bad) => { img.onload = ok; img.onerror = () => bad(new Error("frame didn't load")); img.src = frameUrl(r.frame_url); });
      if (gen !== S.gen) return;
      img.id = "frame";
      $("#frame").replaceWith(img);
      $("#frameinner").classList.remove("hidden");
    } else $("#frameinner").classList.add("hidden");
    S.live = r; S.liveErr = null; S.liveAt = Date.now();
    drawBoxes(); renderStage(); renderTop();
  } catch (err) {
    if (gen !== S.gen) return;
    S.liveErr = err.status === 404 && !S.live ? "The live-view API (hackdash.live) isn't deployed yet, or doesn't know this camera." : err.message;
    renderStage();
  }
  setTimeout(() => liveTick(gen), Math.max(150, 1000 - (performance.now() - t0)));
}
function renderStage() {
  const c = camOf(S.cam), r = S.live, nf = $("#noframe");
  const chips = [];
  if (c?.test_rig) chips.push(`<span class="chip test">test rig</span>`);
  if (r) {
    chips.push(`<span class="chip">≈${fx(r.lag_s, 1)} s behind live</span>`);
    chips.push(r.judge_on ? `<span class="chip green">judge on</span>` : `<span class="chip amber">judge off</span>`);
    chips.push(`<span class="chip">${r.boxes.length} ${r.boxes.length === 1 ? "person" : "people"} in view</span>`);
  }
  if (S.liveErr && r) chips.push(`<span class="chip red" title="${esc(S.liveErr)}">frame ${Math.round((Date.now() - S.liveAt) / 1e3)} s old · retrying</span>`);
  $("#camcap").innerHTML = c ? `<b>${esc(c.name || c.camera_id)}</b> · ${c.live ? `Live${c.fps != null ? ` · ${fx(c.fps, 1)} fps` : ""}` : "Not live"}` : "";
  $("#lag").innerHTML = `<span class="row">${chips.join("")}</span>`;
  let msg = "";
  if (!S.cam) msg = S.camErr ? esc(S.camErr) : "Open a camera on the right to see it live with a box on every person.";
  else if (!r) msg = S.liveErr ? esc(S.liveErr) : "Connecting to the live frame…";
  else if (!r.frame_url) msg = "No frame from the camera's ring right now.";
  nf.innerHTML = msg; nf.classList.toggle("hidden", !msg);
}

// Box state: sent (an open incident this demo launched on the person, or a real judge incident bound to the box),
// else the judge's verdict on the box, else nothing.
function openInc(id) { const x = id && S.inc.get(id); return x && x.status !== "closed" ? x : null; }
function sentInc(b) {
  const mine = openInc(S.sentByTrack.get(b.track_uuid));
  if (mine) return mine;
  for (const x of S.inc.values()) if (x.status !== "closed" && (x.edge_track === b.track_uuid || (b.site_track_id && x.site_track_id === b.site_track_id))) return x;
  return null;
}
function boxKind(b) {
  if (sentInc(b)) return "sent";
  const v = b.label?.verdict;
  return v === "urgent" || v === "deploy" ? "deploy" : v === "watch" ? "watch" : "none";
}
const COLOR = { sent: "#ef5b50", deploy: "#ef5b50", watch: "#e0a43a", none: "#2fbf71" };
function drawBoxes() {
  const r = S.live, img = $("#frame"), cv = $("#boxes");
  if (!r || !r.frame_url || !img.naturalWidth) return;
  const w = img.clientWidth, hh = img.clientHeight, dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(w * dpr); cv.height = Math.round(hh * dpr); cv.style.width = `${w}px`; cv.style.height = `${hh}px`;
  const g = cv.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, hh);
  const sx = w / (r.src_w || img.naturalWidth), sy = hh / (r.src_h || img.naturalHeight);
  const seen = new Set();
  const boxes = r.boxes.map(b => ({ b, t_ns: r.t_ns }));
  // a person being confirmed keeps their chip at the last place they were seen, so the click isn't yanked away
  for (const [tu, p] of S.pending) if (!r.boxes.some(b => b.track_uuid === tu)) boxes.push({ b: p.box, t_ns: p.t_ns, stale: true });
  for (const { b, t_ns, stale } of boxes) {
    const [x1, y1, x2, y2] = b.box, k = boxKind(b);
    const X = x1 * sx, Y = y1 * sy, W = (x2 - x1) * sx, H = (y2 - y1) * sy;
    g.strokeStyle = COLOR[k]; g.lineWidth = k === "none" ? 2 : 3; g.setLineDash(stale ? [5, 4] : []);
    g.strokeRect(X, Y, W, H);
    seen.add(b.track_uuid);
    placeChip(b, t_ns, k, X, Y, Y + H, w, stale);
  }
  for (const [tu, el] of S.chips) if (!seen.has(tu)) { el.remove(); S.chips.delete(tu); }
}
function chipHTML(b, k, stale) {
  const p = S.pending.get(b.track_uuid), L = b.label, inc = sentInc(b), id = shortId(b.track_uuid);
  const sus = L ? `${esc(L.verdict)}${L.why_label ? ` · ${esc(L.why_label)}` : ""}${L.e != null ? ` · E ${fx(L.e, 2)}` : ""}` : "—";
  const facts = L?.facts ? Object.entries(L.facts).slice(0, 2).map(([f, v]) => `${f} ${typeof v === "number" ? fx(v, 2) : v}`).join(" · ") : "";
  // an operator launch is the operator's call, not the judge's: never dress it up as Jev's verdict
  const op = /operator/i.test(`${L?.why_label || ""} ${L?.why || ""}`);
  const why = L && !op ? `<div class="why">${facts ? `${esc(facts)} · ` : ""}scene facts · Jev pointed at this person${L.caption ? `<br>${esc(L.caption)}` : ""}</div>` : "";
  let acts;
  if (inc) acts = `<span class="sentlbl">drone sent</span><button class="no open" data-inc="${esc(inc.id)}">Incident</button>`;
  else if (p?.state === "confirm") acts = `<span>Send drone to ${esc(id)}?</span><button class="yes">Yes</button><button class="no">Cancel</button>`;
  else if (p?.state === "sending") acts = `<span>Sending…</span>`;
  else acts = `<button class="send">Send drone</button>`;
  return `<div><span class="pid">${esc(id)}</span> ${fx(b.conf, 2)} · <span class="sus">${sus}</span>${stale ? ` <span class="sus">(last seen)</span>` : ""}</div>${why}<div class="acts">${acts}</div>`;
}
function placeChip(b, t_ns, k, X, top, bottom, w, stale) {
  const tu = b.track_uuid, html = chipHTML(b, k, stale);
  let el = S.chips.get(tu);
  if (!el) { el = h(`<div class="pchip"></div>`); $("#chips").append(el); S.chips.set(tu, el); }
  if (el.dataset.html !== html) {               // re-render only on change, so a click in flight isn't destroyed
    el.dataset.html = html; el.innerHTML = html;
    el.querySelector(".send")?.addEventListener("click", () => { S.pending.set(tu, { state: "confirm", box: b, t_ns }); drawBoxes(); });
    el.querySelector(".no:not(.open)")?.addEventListener("click", () => { S.pending.delete(tu); drawBoxes(); });
    el.querySelector(".yes")?.addEventListener("click", () => launch(tu));
    el.querySelector(".open")?.addEventListener("click", e => selectInc(e.target.dataset.inc));
  }
  el.className = `pchip ${k}`;
  const flip = top < 64;                        // too close to the top: put the chip under the box
  el.style.transform = flip ? "none" : "";
  el.style.top = `${flip ? bottom + 4 : top}px`;
  el.style.left = `${Math.max(0, Math.min(X, w - el.offsetWidth))}px`;
}
async function launch(tu) {
  const p = S.pending.get(tu);
  if (!p) return;
  // the newest payload's t_ns if the person is still in it, else the instant they were last seen
  const cur = S.live?.boxes.find(b => b.track_uuid === tu);
  const t_ns = cur ? S.live.t_ns : p.t_ns;
  p.state = "sending"; drawBoxes();
  try {
    const r = await post("/launch", `{"camera_id": ${JSON.stringify(S.cam)}, "track_uuid": ${JSON.stringify(tu)}, "t_ns": ${/^\d+$/.test(t_ns) ? t_ns : "0"}}`);
    S.sentByTrack.set(tu, r.id);
    toast(r.already_dispatched ? `Already dispatched: ${shortId(tu)} is on incident ${r.id}`
      : `Drone sent to ${shortId(tu)} · ${r.located ? `located (${r.loc_source || "?"}) ${ll(r.lat, r.lon)}` : "not located"}`);
    await pollIncidents();
    selectInc(r.id);
  } catch (err) { if (err.status !== 401) toast(`Couldn't send the drone: ${err.message}`); }
  S.pending.delete(tu); drawBoxes();
}
window.addEventListener("resize", drawBoxes);

// ------------------------------------------------------------------ incidents + drone messages (left)
async function pollIncidents() {
  try {
    const r = await api("/incidents");
    const rows = Array.isArray(r) ? r : r.incidents || [];
    S.inc = new Map(rows.map(x => [x.id, x])); S.incErr = null; S.incLoaded = true;
  } catch (err) { if (err.status !== 401) S.incErr = err.status === 404 ? "The launch API (hackdash.launch) isn't deployed yet." : `Couldn't load incidents: ${err.message}`; }
  renderPane(); renderTop(); drawBoxes();
}
async function pollMsgs() {
  try {
    const r = await api(`/drone/messages?since=${S.msgSince}`);
    const rows = Array.isArray(r) ? r : r.messages || [];
    for (const m of rows) { S.msgs.push(m); if (m.seq != null) S.msgSince = Math.max(S.msgSince, m.seq); }
    S.msgs = S.msgs.slice(-300); S.msgErr = null;
    if (rows.length) renderPane();
  } catch (err) { if (err.status !== 401) { S.msgErr = err.status === 404 ? "droplink isn't deployed yet." : err.message; renderPane(); } }
}
const incs = () => [...S.inc.values()].sort((a, b) => ((b.status !== "closed") - (a.status !== "closed")) || ((b.opened_at || "") > (a.opened_at || "") ? 1 : -1));
const msgsFor = id => S.msgs.filter(m => m.incident_id === id || m.body?.incident?.id === id);
// forwarded = {attempts, delivered, last: {at, status|error, seq, ...}} (netra-ask's webhook delivery state)
function lastFwd(x) { const f = x.forwarded?.last; return f ? (f.status || f.error || "?") : null; }
const ev = (x, f) => x.evidence?.[f] || x.evidence?.[`${f.split(".")[0]}_url`];
function selectInc(id) { S.sel = id; renderPane(); }
function renderPane() {
  const pane = $("#pane"), keep = pane.scrollTop;
  pane.innerHTML = "";
  const x = S.sel && S.inc.get(S.sel);
  if (x) renderDetail(pane, x);
  else renderList(pane);
  pane.scrollTop = keep;
}
function renderList(pane) {
  const all = incs(), open = all.filter(x => x.status !== "closed");
  pane.append(h(`<div class="qhead"><h2>Drones sent</h2><span class="count ${open.length ? "" : "zero"}">${open.length}</span></div>`));
  if (S.incErr) pane.append(h(`<div class="allquiet"><div class="aq-icon warn">!</div><div class="muted small">${esc(S.incErr)}</div></div>`));
  else if (!S.incLoaded) pane.append(h(`<div class="muted small">Loading…</div>`));
  else if (!all.length) pane.append(h(`<div class="allquiet"><div class="aq-icon">✓</div><div><b>No drone sent</b><div class="muted small">
    Open a camera and press <b>Send drone</b> on a person's box. Incidents launched from here show up here.</div></div></div>`));
  for (const x of all) {
    const f = lastFwd(x), closed = x.status === "closed";
    const b = h(`<button class="qitem ${closed ? "" : "open"}">${ev(x, "crop.jpg") ? `<img class="qthumb" src="${esc(ev(x, "crop.jpg"))}" alt="">` : `<div class="qthumb">${closed ? "✓" : "✈"}</div>`}<div class="qbody">
      <div class="qt">${esc(cap1(x.why_label || String(x.why || "operator launch").replace(/_/g, " ")))}</div>
      <div class="qm">${x.edge_track ? `${esc(shortId(x.edge_track))} · ` : ""}${esc(camOf(x.camera_id)?.name || x.camera_id || "")} · ${esc(ago(x.opened_at))}${closed && x.close_reason ? ` · ${esc(x.close_reason)}` : ""}</div>
      <div class="qchips"><span class="chip ${closed ? "" : "red"}">${closed ? "Closed" : "Open"}</span>
        ${x.located ? `<span class="chip">Located${x.radius_m != null ? ` ±${fx(x.radius_m, 0)} m` : ""}</span>` : `<span class="chip muted">Not located</span>`}
        ${f != null ? `<span class="chip ${/^2/.test(String(f)) ? "green" : "amber"}">forwarded ${esc(x.forwarded.delivered ?? "?")}/${esc(x.forwarded.attempts ?? "?")} · ${esc(f)}</span>` : `<span class="chip muted">not forwarded</span>`}
        ${msgsFor(x.id).length ? `<span class="chip green">drone got ${msgsFor(x.id).length}</span>` : ""}</div></div></button>`);
    b.onclick = () => selectInc(x.id);
    pane.append(b);
  }
  renderLink(pane, S.msgs.slice(-8).reverse(), "Drone link (droplink): last messages");
}
function fact(k, v) { return v == null || v === "" ? "" : `<div class="fk">${esc(k)}</div><div class="fv">${v}</div>`; }
const when = iso => iso ? `${esc(new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" }))} <span class="muted">(${esc(ago(iso))})</span>` : null;
function renderDetail(pane, x) {
  pane.append(btn("← Drones sent", "ghost back", () => selectInc(null)));
  const closed = x.status === "closed";
  pane.append(h(`<div class="dhead"><div class="row"><span class="chip ${closed ? "" : "red"}">${closed ? "Closed" : "Open"}</span>
    <span class="muted small">${esc(x.mode || "")} · ${esc(x.verdict || "")}</span></div><h2>${esc(cap1(x.why_label || String(x.why || "operator launch").replace(/_/g, " ")))}</h2></div>`));
  const F = x.forwarded, L = F?.last;
  const fwd = L ? `${esc(F.delivered ?? "?")} of ${esc(F.attempts ?? "?")} delivered · last ${esc(L.status || L.error || "?")} ${esc(ago(L.at))}${L.netloc ? ` <span class="muted">to ${esc(L.netloc)}</span>` : ""}` : "";
  const cmds = (x.commands || []).map(c => `${esc(c.command)} <span class="muted">${esc(c.delivery_status || "")} · ${esc(ago(c.issued_at))}${c.reason?.code ? ` · ${esc(c.reason.code)}` : ""}</span>`).join("<br>");
  const loc = x.located ? `${ll(x.lat, x.lon)}${x.radius_m != null ? ` <span class="muted">±${fx(x.radius_m, 1)} m</span>` : ""}${x.loc_source ? ` <span class="muted">· ${esc(x.loc_source)}</span>` : ""}` : `<span class="muted">Not located</span>`;
  const mine = x.edge_track || [...S.sentByTrack].find(([, id]) => id === x.id)?.[0];
  if (ev(x, "frame.jpg")) pane.append(h(`<a class="media" href="${esc(ev(x, "frame.jpg"))}" target="_blank"><img src="${esc(ev(x, "frame.jpg"))}" alt="Frame at the click, person boxed"></a>`));
  pane.append(h(`<div class="facts">${fact("Incident", `<span class="mono small">${esc(x.id)}</span>`)}${fact("Camera", esc(camOf(x.camera_id)?.name || x.camera_id))}
    ${fact("Person", mine ? esc(shortId(mine)) : null)}${fact("Site track", x.site_track_id ? `<span class="mono small">${esc(x.site_track_id)}</span>` : null)}
    ${fact("State", esc(x.status || "?") + (x.close_reason || x.closed_reason ? ` <span class="muted">· ${esc(x.close_reason || x.closed_reason)}</span>` : ""))}
    ${fact("Opened", when(x.opened_at))}${fact("Updated", when(x.updated_at))}${fact("Closed", when(x.closed_at))}
    ${fact("Location", loc)}${fact("Operator", x.operator ? esc(x.operator) : null)}${fact("Aborted by", x.aborted_by ? esc(x.aborted_by) : null)}
    ${fact("Forwarded", fwd || `<span class="muted">nothing sent yet</span>`)}${fact("Commands", cmds || null)}
    ${fact("Delivered", msgsFor(x.id).length ? `${msgsFor(x.id).length} message${msgsFor(x.id).length === 1 ? "" : "s"} at the drone receiver` : `<span class="muted">nothing received yet</span>`)}</div>`));
  const row = h(`<div class="row"></div>`);
  if (!closed) {
    const ab = btn("Abort drone", "dangerfill", async () => {
      ab.disabled = true;
      try { const r = await post(`/incidents/${encodeURIComponent(x.id)}/abort`); toast(`Abort sent${r?.command_id ? `: command ${r.command_id}` : ""}`); await pollIncidents(); }
      catch (err) { if (err.status !== 401) toast(`Couldn't abort: ${err.message}`); ab.disabled = false; }
    });
    row.append(ab);
  }
  pane.append(row);
  renderLink(pane, msgsFor(x.id).slice().reverse(), "What the drone received");
}
function renderLink(pane, rows, title) {
  pane.append(h(`<div class="label"><span>${esc(title)}</span><span>${S.msgErr ? "" : rows.length}</span></div>`));
  if (S.msgErr) { pane.append(h(`<div class="muted small">${esc(S.msgErr)}</div>`)); return; }
  if (!rows.length) { pane.append(h(`<div class="muted small">No messages yet.</div>`)); return; }
  const box = h(`<div class="msgs"></div>`);
  for (const m of rows) {
    const b = m.body || {}, I = b.incident, C = b.command;
    // one line of what the drone would act on; the whole signed body folded underneath
    const what = I ? `${I.status} · ${I.verdict}${I.located ? ` · ${ll(I.lat, I.lon)} ±${fx(I.radius_m, 0)} m` : " · not located"}`
      : C ? `${typeof C === "string" ? C : C.command || JSON.stringify(C)}${b.reason?.code ? ` · ${b.reason.code}` : ""}`
      : b.position ? `position ${ll(b.position.lat, b.position.lon)}` : "";
    const body = JSON.stringify(b, null, 1);
    box.append(h(`<div class="msg"><div class="row"><span class="mt">${esc(m.type || "?")}</span>
      <span class="chip ${m.verified ? "green" : "red"}">${m.verified ? "signature ok" : "unverified"}</span>
      <span class="muted">${esc(ago(m.received_at))}${m.seq != null ? ` · seq ${esc(m.seq)}` : ""}</span></div>
      ${what ? `<div>${esc(what)}</div>` : ""}${m.incident_id ? `<div class="muted mono small">${esc(m.incident_id)}</div>` : ""}
      <details><summary class="muted small">signed body</summary><pre>${esc(body.slice(0, 4000))}</pre></details></div>`));
  }
  pane.append(box);
}

// ------------------------------------------------------------------ top bar
function renderTop() {
  const cams = S.cams || [], live = cams.filter(c => c.live).length;
  const open = [...S.inc.values()].filter(x => x.status !== "closed").length;
  const c = camOf(S.cam), r = S.live;
  $("#pills").innerHTML = `
    <span class="pill ${open ? "red solid" : "green"}">${open ? `${open} drone${open === 1 ? "" : "s"} out` : "No drone out"}</span>
    ${S.cams ? `<span class="pill ${!cams.length ? "" : live === cams.length ? "green" : "amber"}">${live}/${cams.length} cameras live</span>` : ""}
    ${r ? `<span class="pill ${r.judge_on ? "green" : "amber"}">${r.judge_on ? "judge on" : "judge off"}</span>` : ""}
    ${c?.test_rig ? `<span class="pill test">${esc(c.name || c.camera_id)}: test rig</span>` : ""}`;
  document.title = `${open ? `(${open}) ` : ""}Send drone · Netra`;
}
function tickClock() { $("#clock").textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" }); }

document.addEventListener("keydown", e => { if (e.key === "Escape") { if (S.pending.size) { S.pending.clear(); drawBoxes(); } else if (S.sel) selectInc(null); } });
renderPane(); renderWall(); renderStage(); tickClock();
pollCams(); pollIncidents(); pollMsgs();
setInterval(pollCams, 5000); setInterval(pollIncidents, 2000); setInterval(pollMsgs, 2000); setInterval(tickClock, 1000);
setInterval(() => { if (S.liveErr) renderStage(); }, 1000);
