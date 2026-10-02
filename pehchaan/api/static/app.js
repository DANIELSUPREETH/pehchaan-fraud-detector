/* Pehchaan analyst console.
 * Plain JavaScript, no build step. Every view reads from the same REST API that other services use,
 * so the console proves the API is complete. Routes live in the URL hash: #/, #/rings, #/ring/<run>/<id>,
 * #/identity/<id>?as_of=YYYY-MM-DD, #/search?q=...
 */
"use strict";

const app = document.getElementById("app");
const SOURCE_LABEL = { bank_kyc: "Bank KYC", telecom: "Telecom", ecommerce: "Shopping" };
const LABEL = {
  SUSPICIOUS_RING: { text: "Suspicious ring", cls: "tag-ring" },
  REVIEW: { text: "Needs a look", cls: "tag-review" },
  LIKELY_FAMILY: { text: "Likely family", cls: "tag-family" },
};
const DECISION = { confirmed_fraud: "Confirmed fraud", false_alarm: "False alarm" };
let refreshTimer = null;

/* ---------- helpers ---------- */
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDate = (iso) => iso ? new Date(String(iso).replace(" ", "T") + (String(iso).includes("Z") ? "" : "Z"))
  .toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) : "";
const fmtDateTime = (iso) => iso ? `${fmtDate(iso)}, ${String(iso).replace(" ", "T").slice(11, 16)}` : "";
const num = (n) => Number(n ?? 0).toLocaleString("en-IN");
const titleCase = (s) => String(s || "").toLowerCase().replace(/[._]+/g, " ").replace(/\b[a-z]/g, (c) => c.toUpperCase()).trim();
const tag = (label) => { const l = LABEL[label] || { text: label, cls: "" }; return `<span class="tag ${l.cls}">${esc(l.text)}</span>`; };
const sources = (list) => list.map((s) => `<span class="src">${esc(SOURCE_LABEL[s] || s)}</span>`).join(", ");
const reasonText = (r) => {
  if (!r) return "";
  if (r === "no matching records") return "First record, no earlier match";
  let m;
  if ((m = r.match(/^matched (\d+) record/))) return `Matched ${m[1]} earlier record${m[1] === "1" ? "" : "s"}`;
  if ((m = r.match(/^merged from (\S+)/))) return `Moved here when ${m[1]} merged in`;
  if ((m = r.match(/^bridged (\d+) identities via (\d+)/))) return `Linked ${m[1]} identities together (${m[2]} matching records)`;
  return r;
};
const verb = (r) => r === "no matching records" ? "started" : /^bridged/.test(r || "") ? "merged into" : "joined";
const bestName = (names) => {
  const cleaned = names.map((n) => String(n).replace(/[._]+/g, " ").replace(/\s+/g, " ").trim());
  const count = {}; cleaned.forEach((n) => { count[n.toLowerCase()] = (count[n.toLowerCase()] || 0) + 1; });
  const words = (n) => n.split(" ").length;
  return cleaned.reduce((a, b) => {
    const ka = [count[a.toLowerCase()], words(a), a.length], kb = [count[b.toLowerCase()], words(b), b.length];
    for (let i = 0; i < 3; i++) if (kb[i] !== ka[i]) return kb[i] > ka[i] ? b : a;
    return a;
  }, cleaned[0] || "");
};
const idLink = (id) => `<a class="mono" href="#/identity/${encodeURIComponent(id)}">${esc(id)}</a>`;

class ApiError extends Error {
  constructor(status, detail) { super(detail); this.status = status; }
}

async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  } catch {
    throw new ApiError(0, "Can't reach the API. Is the server running?");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return body;
}

function showError(err) {
  const noTables = /no such table|does not exist|relation/i.test(err.message);
  app.innerHTML = noTables
    ? `<div class="panel empty"><h2>The database is empty</h2>
        <p>Load some data first, then reload this page:</p>
        <p style="margin-top:10px"><code>python -m pehchaan.generator</code> then <code>python -m pehchaan.offline --fresh</code></p>
        <p style="margin-top:6px">With Docker, start the producer instead (see the README).</p></div>`
    : `<div class="error" role="alert">${esc(err.message)}</div>`;
}

function setNav(section) {
  document.querySelectorAll("nav a").forEach((a) => {
    if (a.dataset.nav === section) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}

/* ---------- router ---------- */
async function route() {
  clearInterval(refreshTimer);
  const hash = location.hash.slice(1) || "/";
  const [path, query = ""] = hash.split("?");
  const params = new URLSearchParams(query);
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  app.innerHTML = `<p class="loading">Loading…</p>`;
  try {
    if (parts.length === 0) { setNav("overview"); await viewOverview(); }
    else if (parts[0] === "rings") { setNav("rings"); await viewRings(params); }
    else if (parts[0] === "ring" && parts.length === 3) { setNav("rings"); await viewRing(parts[1], parts[2]); }
    else if (parts[0] === "identity" && parts[1]) { setNav(""); await viewIdentity(parts[1], params.get("as_of")); }
    else if (parts[0] === "search") { setNav(""); await viewSearch(params.get("q") || ""); }
    else { app.innerHTML = `<div class="panel empty"><h2>Page not found</h2><p><a href="#/">Go to the overview</a></p></div>`; }
  } catch (err) {
    showError(err);
  }
  if (!location.hash.startsWith("#/search")) document.getElementById("q").value = "";
}

/* ---------- overview ---------- */
async function viewOverview() {
  const [ov, act, rings] = await Promise.all([api("/overview"), api("/activity?limit=12"), api("/rings?label=SUSPICIOUS_RING")]);
  const s = ov.stats;
  if (!s.records) {
    app.innerHTML = `<div class="panel empty"><h2>No records yet</h2>
      <p>Run <code>python -m pehchaan.generator</code> and <code>python -m pehchaan.offline --fresh</code>,
      or start the Kafka producer. This page refreshes on its own.</p></div>`;
    scheduleRefresh();
    return;
  }
  const total = Object.values(s.records_by_source).reduce((a, b) => a + b, 0) || 1;
  const open = rings.components.filter((c) => !c.review).slice(0, 6);
  app.innerHTML = `
    <div class="page-head">
      <div><h1>Overview</h1>
        <p class="muted">${ov.analysis_run ? `Latest graph analysis: <span class="mono">${esc(ov.analysis_run)}</span>` : "No graph analysis yet. Run <code>python -m pehchaan.analyze</code>."}</p></div>
      <span class="live" id="live">Live, refreshing every 5 seconds</span>
    </div>
    <div class="band">
      <div><b>${num(s.records)}</b><span>records resolved</span></div>
      <div><b>${num(s.identities_active)}</b><span>people (active identities)</span></div>
      <div><b>${num(s.identities_merged_away)}</b><span>identities merged</span></div>
      <div class="${ov.suspicious_open ? "alert" : ""}"><b>${num(ov.suspicious_open)}</b><span>suspicious groups to review, of ${num(ov.suspicious_total)}</span></div>
    </div>
    <div class="grid-side">
      <div>
        <div class="panel">
          <div class="panel-head"><h2>Needs review</h2><a href="#/rings">Open the queue</a></div>
          ${open.length ? `<div class="table-wrap"><table><thead><tr><th>Group</th><th class="num">Risk</th><th class="num">People</th><th>Strongest signal</th></tr></thead><tbody>
            ${open.map((c) => `<tr class="clickable" data-href="#/ring/${encodeURIComponent(rings.run_id)}/${c.component_id}">
              <td><a href="#/ring/${encodeURIComponent(rings.run_id)}/${c.component_id}">Group ${c.component_id}</a></td>
              <td class="num">${c.risk_score > 0 ? "+" : ""}${c.risk_score}</td><td class="num">${c.features.size}</td>
              <td>${esc(c.reasons[0] || "")}</td></tr>`).join("")}
            </tbody></table></div>`
            : `<p class="muted">${ov.suspicious_total ? "Every suspicious group has been reviewed." : "No suspicious groups in the latest analysis."}</p>`}
          ${Object.keys(ov.decisions).length ? `<p class="muted" style="margin-top:12px">Decisions so far: ${Object.entries(ov.decisions).map(([d, n]) => `${esc(DECISION[d] || d)} ${n}`).join(", ")}</p>` : ""}
        </div>
        <div class="panel">
          <h2 style="margin-bottom:12px">Records by source</h2>
          <div class="sources">${Object.entries(s.records_by_source).map(([src, n]) => `
            <div class="source-row"><span>${esc(SOURCE_LABEL[src] || src)}</span><div class="bar"><i style="width:${(n / total) * 100}%"></i></div><span class="num mono">${num(n)}</span></div>`).join("")}
          </div>
        </div>
      </div>
      <div class="panel" id="feedPanel">${feedHtml(act)}</div>
    </div>`;
  bindRowLinks();
  scheduleRefresh();
}

function feedHtml(act) {
  return `
    <div class="panel-head"><h2>Latest records</h2></div>
    <div class="feed">${act.recent_records.map((r) => `
      <div class="feed-item"><span class="when">${esc(SOURCE_LABEL[r.source] || r.source)}<br>${esc(fmtDate(r.ingested_at))}</span>
        <span><b>${esc(r.name_as_written)}</b> ${verb(r.assigned_because)} ${idLink(r.identity_id)}<br><span class="muted" style="font-size:14px">${esc(reasonText(r.assigned_because))}</span></span></div>`).join("")}
    </div>
    ${act.recent_merges.length ? `<h2 style="margin:18px 0 8px">Latest merges</h2><div class="feed">${act.recent_merges.slice(0, 5).map((m) => `
      <div class="feed-item"><span class="when">${esc(fmtDate(m.merged_at))}</span>
        <span>${idLink(m.identity_id)} merged into ${idLink(m.merged_into)}</span></div>`).join("")}</div>` : ""}`;
}

function scheduleRefresh() {
  refreshTimer = setInterval(async () => {
    if (document.hidden || location.hash.slice(1).replace(/^\/$/, "") !== "") return;
    try {
      const [ov, act] = await Promise.all([api("/overview"), api("/activity?limit=12")]);
      if (!document.getElementById("feedPanel")) { if (ov.stats.records) route(); return; }
      const band = app.querySelectorAll(".band b");
      [ov.stats.records, ov.stats.identities_active, ov.stats.identities_merged_away, ov.suspicious_open]
        .forEach((v, i) => { if (band[i]) band[i].textContent = num(v); });
      document.getElementById("feedPanel").innerHTML = feedHtml(act);
      const live = document.getElementById("live");
      if (live) { live.classList.remove("paused"); live.textContent = `Live, updated ${new Date().toLocaleTimeString()}`; }
    } catch {
      const live = document.getElementById("live");
      if (live) { live.classList.add("paused"); live.textContent = "Paused: can't reach the API"; }
    }
  }, 5000);
}

/* ---------- review queue ---------- */
async function viewRings(params) {
  const label = params.get("label") || "SUSPICIOUS_RING";
  const hideReviewed = params.get("open") === "1";
  const data = await api(`/rings?label=${encodeURIComponent(label)}`);
  const counts = data.label_counts || {};
  if (!data.run_id && !Object.keys(counts).length) {
    app.innerHTML = `<div class="panel empty"><h2>No graph analysis yet</h2>
      <p>Run <code>python -m pehchaan.analyze</code> to group identities that share phones, devices or addresses.</p></div>`;
    return;
  }
  const rows = data.components.filter((c) => !(hideReviewed && c.review));
  const tabHref = (l) => `#/rings?label=${l}${hideReviewed ? "&open=1" : ""}`;
  app.innerHTML = `
    <div class="page-head"><div><h1>Review queue</h1>
      <p class="muted">Groups of identities that share a phone, device or address, scored on behaviour. ${num(data.reviewed)} reviewed so far.</p></div></div>
    <div class="tabs" role="group" aria-label="Filter by label">
      ${Object.keys(LABEL).map((l) => `<a href="${tabHref(l)}" aria-current="${l === label}">${esc(LABEL[l].text)} (${num(counts[l] || 0)})</a>`).join("")}
      <label><input type="checkbox" id="hideReviewed" ${hideReviewed ? "checked" : ""}> Hide reviewed</label>
    </div>
    <div class="panel">${rows.length ? `<div class="table-wrap"><table class="wide">
      <thead><tr><th>Group</th><th>Label</th><th class="num">Risk</th><th class="num">People</th><th class="num">Appeared within</th><th class="num">Bank KYC</th><th>Strongest signal</th><th>Decision</th></tr></thead>
      <tbody>${rows.map((c) => {
        const href = `#/ring/${encodeURIComponent(data.run_id)}/${c.component_id}`;
        return `<tr class="clickable" data-href="${href}">
          <td><a href="${href}">Group ${c.component_id}</a></td><td>${tag(c.label)}</td>
          <td class="num">${c.risk_score > 0 ? "+" : ""}${c.risk_score}</td><td class="num">${c.features.size}</td>
          <td class="num">${Math.round(c.features.first_seen_span_days)} days</td><td class="num">${Math.round(c.features.kyc_fraction * 100)}%</td>
          <td>${esc(c.reasons[0] || "No strong signal")}</td>
          <td>${c.review ? `<span class="tag ${c.review.decision === "confirmed_fraud" ? "tag-ring" : "tag-family"}">${esc(DECISION[c.review.decision])}</span>` : `<span class="muted">Open</span>`}</td></tr>`;
      }).join("")}</tbody></table></div>`
      : `<p class="empty">${hideReviewed ? "Everything in this list has been reviewed." : "No groups with this label."}</p>`}</div>`;
  document.getElementById("hideReviewed").addEventListener("change", (e) => {
    location.hash = `#/rings?label=${label}${e.target.checked ? "&open=1" : ""}`;
  });
  bindRowLinks();
}

/* ---------- one group ---------- */
async function viewRing(runId, componentId) {
  const d = await api(`/rings/${encodeURIComponent(runId)}/${encodeURIComponent(componentId)}`);
  const f = d.features;
  app.innerHTML = `
    <div class="page-head"><div><p><a href="#/rings?label=${esc(d.label)}">Review queue</a></p>
      <h1>Group ${d.component_id} ${tag(d.label)}</h1>
      <p class="muted">${f.size} identities, risk score ${d.risk_score > 0 ? "+" : ""}${d.risk_score}. Analysis run <span class="mono">${esc(d.run_id)}</span>.</p></div></div>
    <div class="grid-side">
      <div class="panel graph">
        <div class="panel-head"><h2>How they connect</h2><span class="muted" style="font-size:14px">Select a person to open them</span></div>
        ${graphSvg(d)}
        <div class="legend"><span><i style="background:var(--minus)"></i>Shared device</span><span><i style="background:var(--marigold)"></i>Shared phone</span>
          <span><i style="background:var(--muted)"></i>Shared address</span><span>Filled circle: has bank KYC</span></div>
      </div>
      <div>
        <div class="panel">
          <h2 style="margin-bottom:10px">Why it was scored this way</h2>
          ${d.reasons.length ? `<ul class="reasons">${d.reasons.map((r) => `<li>${esc(r.charAt(0).toUpperCase() + r.slice(1))}</li>`).join("")}</ul>` : `<p class="muted">No strong signals either way.</p>`}
          <dl class="features" style="margin-top:14px">
            <dt>Appeared within</dt><dd>${f.first_seen_span_days} days</dd>
            <dt>Share with bank KYC</dt><dd>${Math.round(f.kyc_fraction * 100)}%</dd>
            <dt>Most people on one device</dt><dd>${f.max_identities_per_device}</dd>
            <dt>Most people on one phone</dt><dd>${f.max_identities_per_phone}</dd>
            <dt>Share at one address</dt><dd>${Math.round(f.address_share * 100)}%</dd>
          </dl>
        </div>
        <div class="panel decision" id="decision">${decisionHtml(d)}</div>
      </div>
    </div>
    <div class="panel" style="margin-top:16px">
      <h2 style="margin-bottom:10px">People in this group</h2>
      <div class="table-wrap"><table class="medium"><thead><tr><th>Identity</th><th>Name</th><th>Sources</th><th class="num">Records</th><th>First seen</th></tr></thead>
      <tbody>${d.nodes.map((n) => `<tr class="clickable" data-href="#/identity/${encodeURIComponent(n.identity_id)}">
        <td>${idLink(n.identity_id)}</td><td>${esc(n.display_name)}</td><td>${sources(n.sources)}</td>
        <td class="num">${n.record_count}</td><td>${esc(fmtDate(n.first_seen))}</td></tr>`).join("")}</tbody></table></div>
    </div>`;
  bindRowLinks();
  bindDecision(d);
  app.querySelectorAll(".graph .node").forEach((g) => {
    const open = () => { location.hash = `#/identity/${encodeURIComponent(g.dataset.id)}`; };
    g.addEventListener("click", open);
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
  });
}

function decisionHtml(d) {
  const r = d.review;
  return `<h2>Your decision</h2>
    <p class="muted" style="font-size:14px">Saved decisions become labelled examples for improving the scoring later.</p>
    <div class="actions">
      <button type="button" class="btn-fraud" data-decision="confirmed_fraud" aria-pressed="${r?.decision === "confirmed_fraud"}">Confirm fraud</button>
      <button type="button" class="btn-ok" data-decision="false_alarm" aria-pressed="${r?.decision === "false_alarm"}">Mark false alarm</button>
    </div>
    <label for="note" class="muted" style="font-size:14px">Note (optional)</label>
    <textarea id="note" maxlength="500" placeholder="What did you check?">${esc(r?.note || "")}</textarea>
    <p class="saved" id="savedMsg">${r ? `Saved as ${esc(DECISION[r.decision])} on ${esc(fmtDateTime(r.reviewed_at))} UTC.` : "Not reviewed yet."}</p>`;
}

function bindDecision(d) {
  const box = document.getElementById("decision");
  box.querySelectorAll("[data-decision]").forEach((btn) => btn.addEventListener("click", async () => {
    box.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    const msg = document.getElementById("savedMsg");
    msg.textContent = "Saving…";
    try {
      const saved = await api(`/rings/${encodeURIComponent(d.run_id)}/${d.component_id}/review`, {
        method: "POST", body: JSON.stringify({ decision: btn.dataset.decision, note: document.getElementById("note").value }),
      });
      d.review = { decision: saved.decision, note: document.getElementById("note").value, reviewed_at: saved.reviewed_at };
      box.innerHTML = decisionHtml(d);
      bindDecision(d);
    } catch (err) {
      msg.textContent = `Not saved: ${err.message}`;
      box.querySelectorAll("button").forEach((b) => { b.disabled = false; });
    }
  }));
}

function graphSvg(d) {
  const W = 520, H = 400, cx = W / 2, cy = H / 2, R = d.nodes.length <= 3 ? 110 : 150;
  const pos = {};
  d.nodes.forEach((n, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / d.nodes.length;
    pos[n.identity_id] = { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a), a };
  });
  const colour = (k) => k.includes("device") ? "var(--minus)" : k.includes("phone") ? "var(--marigold)" : "var(--muted)";
  const edges = d.edges.map((e) => {
    const p = pos[e.a], q = pos[e.b];
    return `<line x1="${p.x}" y1="${p.y}" x2="${q.x}" y2="${q.y}" stroke="${colour(e.kinds)}" stroke-width="${1 + e.kinds.length}" stroke-opacity="0.75"><title>Share: ${esc(e.kinds.join(", "))}</title></line>`;
  }).join("");
  const nodes = d.nodes.map((n) => {
    const p = pos[n.identity_id];
    const lx = cx + (R + 20) * Math.cos(p.a), ly = cy + (R + 20) * Math.sin(p.a);
    const anchor = Math.abs(Math.cos(p.a)) < 0.3 ? "middle" : Math.cos(p.a) > 0 ? "start" : "end";
    const kyc = n.sources.includes("bank_kyc");
    return `<g class="node" data-id="${esc(n.identity_id)}" tabindex="0" role="link" aria-label="Open ${esc(n.display_name)}, ${esc(n.identity_id)}">
      <title>${esc(n.display_name)} (${esc(n.identity_id)}), ${n.record_count} records</title>
      <circle cx="${p.x}" cy="${p.y}" r="11" fill="${kyc ? "var(--stamp)" : "var(--surface)"}" stroke="var(--stamp)" stroke-width="2.5"></circle>
      <text x="${lx}" y="${ly + 5}" text-anchor="${anchor}" font-size="13" fill="var(--ink)">${esc(n.display_name)}</text></g>`;
  }).join("");
  return `<svg viewBox="-90 0 ${W + 180} ${H}" role="img" aria-label="Graph of ${d.nodes.length} identities and what they share">${edges}${nodes}</svg>`;
}

/* ---------- identity ---------- */
async function viewIdentity(id, asOf) {
  const q = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
  let view;
  try {
    view = await api(`/identities/${encodeURIComponent(id)}${q}`);
  } catch (err) {
    if (err.status === 404 && asOf) {  // did not exist yet at that date: say so, keep the date picker
      app.innerHTML = identityHeader(id, asOf, null) + `<div class="panel empty"><h2>Not created yet</h2><p>${esc(err.message)}</p></div>`;
      bindAsOf(id);
      return;
    }
    throw err;
  }
  const [history, explain] = await Promise.all([
    api(`/identities/${encodeURIComponent(id)}/history`), api(`/identities/${encodeURIComponent(id)}/explain`)]);
  const name = view.records.length ? titleCase(bestName(view.records.map((r) => r.name_as_written))) : id;
  app.innerHTML = identityHeader(id, asOf, view, name) +
    (view.status === "merged" ? `<div class="notice">This identity was merged into ${idLink(view.merged_into)}. Its records now live there. Pick an earlier date to see it before the merge.</div>` : "") +
    `<div class="panel">
      <div class="panel-head"><h2>Records ${asOf ? `on ${esc(fmtDate(asOf))}` : "today"}</h2><span class="muted">${view.record_count} from ${sources(view.sources) || "no sources"}</span></div>
      ${view.records.length ? `<div class="table-wrap"><table class="wide"><thead><tr><th>Record</th><th>Source</th><th class="nowrap">Received</th><th>Name as written</th><th>Birth date</th><th>Phone</th><th>Email</th><th>Address</th></tr></thead><tbody>
      ${view.records.map((r) => `<tr><td class="mono nowrap">${esc(r.record_id)}</td><td class="nowrap">${esc(SOURCE_LABEL[r.source] || r.source)}</td><td class="nowrap">${esc(fmtDate(r.ingested_at))}</td>
        <td><b>${esc(r.name_as_written)}</b>${r.data_quality_flags.length ? `<br><span class="flags">${esc(r.data_quality_flags.join(", ").replace(/_/g, " "))}</span>` : ""}</td>
        <td class="mono nowrap">${esc(r.date_of_birth || "")}</td><td class="mono nowrap">${esc(r.phones.join(", "))}</td><td class="mono">${esc(r.email || "")}</td>
        <td class="addr">${esc(r.address || "")}${r.pincode ? ` <span class="muted">${esc(r.pincode)}</span>` : ""}</td></tr>`).join("")}
      </tbody></table></div>` : `<p class="muted">No records at this date.</p>`}
    </div>
    <div class="grid-2" style="margin-top:16px">
      <div class="panel"><h2 style="margin-bottom:10px">Why these records are linked</h2>
        ${explain.links.length ? explain.links.map((l) => `<div class="link-row">
          <span class="mono">${esc(l.records[0])}</span> and <span class="mono">${esc(l.records[1])}</span>
          <span class="score">score ${Number(l.score).toFixed(1)}</span> <span class="muted" style="font-size:13px">${esc(fmtDate(l.linked_at))}</span>
          <div class="evidence">${l.evidence.map((e) => { const m = e.match(/^(.*) \(([+-][\d.]+)\)$/); const pts = m ? parseFloat(m[2]) : 0;
            return `<span class="chip ${pts >= 0 ? "plus" : "minus"}">${esc(m ? `${m[1]} ${m[2]}` : e)}</span>`; }).join("")}</div></div>`).join("")
          : `<p class="muted">${view.record_count <= 1 ? "Only one record, so nothing to link yet." : "No stored links between the current records."}</p>`}
      </div>
      <div class="panel"><h2 style="margin-bottom:10px">History</h2>
        <ul class="timeline">${history.events.map((e) => `<li><span class="muted">${esc(fmtDateTime(e.joined_at))}</span>
          <span><span class="mono">${esc(e.record_id)}</span>: ${esc(reasonText(e.reason))}${e.left_at ? `<br><span class="muted">Left ${esc(fmtDateTime(e.left_at))}</span>` : ""}</span></li>`).join("")}
          ${history.merged_at ? `<li><span class="muted">${esc(fmtDateTime(history.merged_at))}</span><span>Merged into ${idLink(history.merged_into)}</span></li>` : ""}
        </ul>
      </div>
    </div>`;
  bindAsOf(id);
}

function identityHeader(id, asOf, view, name) {
  return `<div class="page-head">
    <div><h1>${esc(name || id)}</h1>
      <p class="muted"><span class="mono">${esc(id)}</span>${view ? ` ${view.status === "merged" ? `<span class="tag tag-merged">Merged</span>` : `<span class="tag tag-active">Active</span>`} created ${esc(fmtDate(view.created_at))}` : ""}</p></div>
    <form class="as-of" id="asOfForm">
      <label for="asOf">View as of</label>
      <input type="date" id="asOf" value="${esc(asOf || "")}" min="2026-01-01" max="2026-12-31">
      <button type="submit">Show</button>
      ${asOf ? `<a class="btn" href="#/identity/${encodeURIComponent(id)}">Today</a>` : ""}
    </form></div>`;
}

function bindAsOf(id) {
  document.getElementById("asOfForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = document.getElementById("asOf").value;
    location.hash = `#/identity/${encodeURIComponent(id)}${v ? `?as_of=${v}` : ""}`;
  });
}

/* ---------- search ---------- */
async function viewSearch(q) {
  document.getElementById("q").value = q;
  if (!q.trim()) { app.innerHTML = `<div class="panel empty"><h2>Search</h2><p>Type a name, phone number or email above.</p></div>`; return; }
  let res;
  try {
    res = await api(`/search?q=${encodeURIComponent(q)}`);
  } catch (err) {
    if (err.status === 400) { app.innerHTML = `<div class="panel empty"><h2>Can't search for that</h2><p>${esc(err.message)}</p></div>`; return; }
    throw err;
  }
  const how = { name: "Name search is phonetic, so different spellings match.", phone: "Any phone format works; it's normalised first.", email: "" }[res.searched_as];
  app.innerHTML = `
    <div class="page-head"><div><h1>Results for “${esc(q)}”</h1>
      <p class="muted">Searched as ${esc(res.searched_as)}. ${esc(how)} ${res.results.length} ${res.results.length === 1 ? "person" : "people"}${res.truncated ? " (first 50 shown)" : ""}.</p></div></div>
    <div class="panel">${res.results.length ? `<div class="table-wrap"><table><thead><tr><th>Identity</th><th>Name</th><th>Sources</th><th class="num">Records</th></tr></thead><tbody>
      ${res.results.map((r) => `<tr class="clickable" data-href="#/identity/${encodeURIComponent(r.identity_id)}">
        <td>${idLink(r.identity_id)}</td><td>${esc(r.display_name)}</td><td>${sources(r.sources)}</td><td class="num">${r.record_count}</td></tr>`).join("")}
      </tbody></table></div>
      ${res.searched_as === "phone" && res.results.length > 1 ? `<p class="muted" style="margin-top:12px">${esc(res.note)}</p>` : ""}`
      : `<p class="empty">Nobody matches. Try another spelling, or search by phone or email.</p>`}</div>`;
  bindRowLinks();
}

/* ---------- shared bindings ---------- */
function bindRowLinks() {
  app.querySelectorAll("tr.clickable").forEach((tr) => tr.addEventListener("click", (e) => {
    if (e.target.closest("a, button, input")) return;
    location.hash = tr.dataset.href;
  }));
}

document.getElementById("searchForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = document.getElementById("q").value.trim();
  if (q) location.hash = `#/search?q=${encodeURIComponent(q)}`;
});
window.addEventListener("hashchange", () => { route(); app.focus({ preventScroll: true }); window.scrollTo(0, 0); });
route();
