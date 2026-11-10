(() => {
  "use strict";

  const DOC_NAMES = { fnol_form: "FNOL form", loss_report: "Loss report", repair_estimate: "Repair estimate" };
  const DOC_ORDER = ["fnol_form", "loss_report", "repair_estimate"];
  const LABELS = {
    claim_ref: "Claim reference", policy_number: "Policy number", insured_name: "Insured",
    risk_address: "Risk address", occupancy_type: "Occupancy", date_of_loss: "Date of loss",
    date_reported: "Date reported", cause_of_loss: "Cause of loss",
    building_damage_estimate: "Building damage", contents_damage_estimate: "Contents damage",
    business_interruption: "Business interruption", third_party_involved: "Third party involved",
    third_party_name: "Third party name", reporter_name: "Reporter", reporter_phone: "Reporter phone",
    loss_description: "Description of loss",
  };
  const FLAGGED = ["conflict", "ungrounded", "unparsed"];

  const $ = (selector, root = document) => root.querySelector(selector);
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (n) => "£" + Number(n).toLocaleString("en-GB");
  const upper = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const state = { claims: [], filter: "all", id: null, detail: null, selection: [], doc: "fnol_form" };

  async function api(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`${path} returned ${response.status}`);
    return response.json();
  }

  /* Queue */

  function renderQueue() {
    const reviewCount = state.claims.filter((c) => c.review_required).length;
    $("#count-all").textContent = state.claims.length;
    $("#count-review").textContent = reviewCount;
    document.querySelectorAll(".seg button").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.filter === state.filter)));

    const rows = state.claims.filter((c) => state.filter === "all" || c.review_required);
    $("#queue").innerHTML = rows.length ? rows.map((c) => {
      const total = Number.isFinite(c.building_damage) && Number.isFinite(c.contents_damage)
        ? money(c.building_damage + c.contents_damage) : "";
      const meta = [upper(c.cause), total].filter(Boolean).join(", ");
      const flags = c.flags.length
        ? `<span class="qflag" title="${c.flags.length} to review"><span aria-hidden="true">${c.flags.length}</span><span class="visually-hidden">${c.flags.length} to review</span></span>` : "";
      return `<li><button type="button" class="qrow" data-id="${esc(c.claim_id)}" aria-current="${c.claim_id === state.id}">
        <span class="qid">${esc(c.claim_id)}</span>
        <span class="qname">${esc(c.insured || "Insured not recorded")}</span>
        <span class="qmeta">${esc(meta)}</span>${flags}</button></li>`;
    }).join("") : `<li class="empty">No claims match this filter.</li>`;
  }

  /* Claim column */

  function statusChip(f) {
    switch (f.status) {
      case "ok": return ["ok", f.agreeing_docs > 1 ? `Found in ${f.agreeing_docs} documents` : "Found in 1 document"];
      case "conflict": return ["conflict", "Documents disagree"];
      case "missing": return ["missing", f.stated_missing && f.stated_missing.length ? "Not recorded" : "Not found"];
      case "not_applicable": return ["na", "Not applicable"];
      default: return ["check", "Check on page"];
    }
  }

  function renderClaim() {
    const { record, briefing } = state.detail;
    const fields = record.fields;
    const insured = fields.insured_name && fields.insured_name.value;

    const attention = briefing.attention.length ? `
      <section class="block attention"><h2>Needs your attention</h2><ul>
        ${briefing.attention.map((a) => `<li><div class="attn" data-type="${esc(a.type)}" data-field="${esc(a.field)}">
          <p>${esc(a.text)}</p><button type="button" class="btn" data-select="${esc(a.field)}">Show on page</button></div></li>`).join("")}
      </ul></section>` : "";

    const note = briefing.sentences.map((s, i) => `<li><button type="button"
      class="line${s.flagged ? " flagged" : ""}" data-sentence="${i}"><span>${esc(s.text)}</span></button></li>`).join("");

    const rows = Object.keys(LABELS).map((name) => {
      const f = fields[name] || { status: "missing" };
      const [kind, text] = statusChip(f);
      const value = f.value ? esc(String(f.value).length > 80 ? String(f.value).slice(0, 80) + "…" : f.value)
        : `<span class="none">${f.status === "not_applicable" ? "None" : "Not recorded"}</span>`;
      return `<li><button type="button" class="frow" data-select="${name}">
        <span class="flabel">${esc(LABELS[name])}</span>
        <span class="fvalue${f.value ? "" : " none"}" title="${esc(f.value || "")}">${value}</span>
        <span class="chip ${kind}">${esc(text)}</span></button></li>`;
    }).join("");

    const t = record.timings || {};
    const cost = record.cost || {};
    const parts = [];
    if (Number.isFinite(t.total_seconds)) parts.push(`Prepared in ${t.total_seconds} seconds`);
    if (Number.isFinite(cost.total_usd)) parts.push(`at a cost of $${cost.total_usd.toFixed(4)}`);
    const provenance = `Read from ${record.documents.length} documents by Document AI and Gemini.${parts.length ? " " + parts.join(" ") + "." : ""}
      Every value above links to a line on the page.`;

    $("#claim").innerHTML = `
      <header class="claim-head">
        <h1${briefing.headline_flagged ? ' class="flagged"' : ""}>${esc(briefing.headline)}</h1>
        <p>${esc(record.claim_id)}${insured ? ", " + esc(insured) : ""}</p>
      </header>
      ${attention}
      <section class="block"><h2>Briefing</h2><ul class="note">${note}</ul></section>
      <section class="block"><h2>What we read</h2><ul class="fields">${rows}</ul></section>
      <p class="provenance">${esc(provenance)}</p>`;
  }

  /* Evidence on the page */

  function computeMarks() {
    const fields = state.detail.record.fields;
    const marks = [];
    for (const name of state.selection) {
      const f = fields[name];
      if (!f) continue;
      const kind = FLAGGED.includes(f.status) ? "flag" : "primary";
      for (const ev of f.evidence || []) marks.push({ doc: f.source_doc, page: ev.page, box: ev.box, kind, field: name, text: ev.text });
      for (const c of f.conflicts || []) for (const ev of c.evidence || []) marks.push({ doc: c.doc, page: ev.page, box: ev.box, kind: "alt", field: name, text: ev.text });
      for (const s of f.stated_missing || []) for (const ev of s.evidence || []) marks.push({ doc: s.doc, page: ev.page, box: ev.box, kind: "alt", field: name, text: ev.text });
    }
    return marks.filter((m) => Array.isArray(m.box));
  }

  function renderViewer() {
    const { record } = state.detail;
    const marks = computeMarks();
    const counts = Object.fromEntries(DOC_ORDER.map((d) => [d, marks.filter((m) => m.doc === d).length]));
    if (marks.length && !counts[state.doc]) state.doc = marks[0].doc;

    $("#tabs").innerHTML = DOC_ORDER.map((d) => `<button type="button" data-doc="${d}" aria-pressed="${d === state.doc}">
      ${esc(DOC_NAMES[d])}${counts[d] ? `<span class="n" title="${counts[d]} highlighted"><span aria-hidden="true">${counts[d]}</span><span class="visually-hidden">${counts[d]} highlighted</span></span>` : ""}</button>`).join("");

    const doc = (record.documents || []).find((d) => d.type === state.doc);
    const pages = doc ? doc.pages : 1;
    let html = "";
    for (let p = 1; p <= pages; p++) {
      const boxes = marks.filter((m) => m.doc === state.doc && m.page === p).map((m) => {
        const [x0, y0, x1, y1] = m.box;
        const padX = 0.006, padY = 0.004;
        const style = `left:${((x0 - padX) * 100).toFixed(2)}%;top:${((y0 - padY) * 100).toFixed(2)}%;width:${((x1 - x0 + 2 * padX) * 100).toFixed(2)}%;height:${((y1 - y0 + 2 * padY) * 100).toFixed(2)}%`;
        return `<div class="mark ${m.kind}" style="${style}" title="${esc(LABELS[m.field] || m.field)}: ${esc(m.text)}"></div>`;
      }).join("");
      html += `<div class="page"><img src="/api/pages/${encodeURIComponent(record.claim_id)}/${state.doc}/${p}"
        alt="${esc(DOC_NAMES[state.doc])}, page ${p} of ${esc(record.claim_id)}">${boxes}</div>`;
    }
    $("#sheet").innerHTML = html;
    $("#sheet").querySelectorAll(".page img").forEach((img) => {
      img.addEventListener("error", () => {
        img.closest(".page").outerHTML = `<p class="broken">This page image is not available. Check that the pages have been rendered for this claim.</p>`;
      });
    });
    const first = $("#sheet .mark");
    if (first) first.scrollIntoView({ block: "center", behavior: reduceMotion ? "auto" : "smooth" });

    renderCaption(marks);
  }

  function renderCaption(marks) {
    const fields = state.detail.record.fields;
    if (!state.selection.length) {
      $("#caption").innerHTML = "<p>Select a sentence or a field to see where it came from on the page.</p>";
      return;
    }
    const lines = state.selection.map((name) => {
      const f = fields[name];
      if (!f) return "";
      const label = esc(LABELS[name] || name);
      if (f.status === "missing") {
        const said = (f.stated_missing || []).map((s) => `${esc(DOC_NAMES[s.doc] || s.doc)} says “${esc(s.value)}”`).join("; ");
        return `<p><strong>${label}</strong>: ${said ? "not recorded. " + said + "." : "not found in any document, so there is nothing to highlight."}</p>`;
      }
      if (f.status === "not_applicable") return `<p><strong>${label}</strong>: not applicable for this claim.</p>`;
      const alt = (f.conflicts || []).map((c) => `<span class="alt">${esc(DOC_NAMES[c.doc] || c.doc)} says ${esc(c.value)}</span>`).join("; ");
      return `<p><strong>${label}</strong>: ${esc(f.value)} <span>(${esc(DOC_NAMES[f.source_doc] || f.source_doc || "")})</span>${alt ? ". " + alt : ""}</p>`;
    });
    $("#caption").innerHTML = lines.join("");
  }

  function refreshSelectionState() {
    const sel = new Set(state.selection);
    const sentences = state.detail.briefing.sentences;
    document.querySelectorAll(".line").forEach((el) => {
      const s = sentences[Number(el.dataset.sentence)];
      const on = s.fields.length && s.fields.some((f) => sel.has(f)) && s.fields.filter((f) => state.detail.record.fields[f] && state.detail.record.fields[f].value).every((f) => sel.has(f));
      el.classList.toggle("on", Boolean(on));
      el.setAttribute("aria-pressed", String(Boolean(on)));
    });
    document.querySelectorAll(".frow").forEach((el) => {
      const on = sel.has(el.dataset.select);
      el.classList.toggle("on", on);
      el.setAttribute("aria-pressed", String(on));
    });
    document.querySelectorAll(".attn").forEach((el) => el.classList.toggle("on", sel.has(el.dataset.field) && state.selection.length === 1));
  }

  function select(fields) {
    state.selection = fields;
    refreshSelectionState();
    renderViewer();
  }

  /* Loading */

  async function selectClaim(id) {
    state.id = id;
    renderQueue();
    $("#claim").innerHTML = `<p class="empty">Loading claim…</p>`;
    try {
      state.detail = await api(`/api/claims/${encodeURIComponent(id)}`);
    } catch (error) {
      $("#claim").innerHTML = `<p class="empty">This claim could not be loaded. Refresh the page. If it keeps failing, the service may be paused.</p>`;
      return;
    }
    renderClaim();
    const { briefing, record } = state.detail;
    let first = [];
    if (briefing.attention.length) {
      first = [briefing.attention[0].field];
      state.doc = (record.fields[first[0]] || {}).source_doc || "fnol_form";
    } else {
      const s = briefing.sentences.find((x) => x.fields.includes("building_damage_estimate"));
      first = s ? s.fields.filter((f) => record.fields[f] && record.fields[f].value) : [];
      state.doc = "loss_report";
    }
    select(first);
    $("#claim").scrollTop = 0;
  }

  function wire() {
    $("#queue").addEventListener("click", (e) => {
      const row = e.target.closest(".qrow");
      if (row) selectClaim(row.dataset.id);
    });
    document.querySelector(".seg").addEventListener("click", (e) => {
      const button = e.target.closest("button");
      if (!button) return;
      state.filter = button.dataset.filter;
      renderQueue();
    });
    $("#claim").addEventListener("click", (e) => {
      const line = e.target.closest(".line");
      if (line) {
        const s = state.detail.briefing.sentences[Number(line.dataset.sentence)];
        select(s.fields.filter((f) => state.detail.record.fields[f] && state.detail.record.fields[f].value || (state.detail.record.fields[f] || {}).status === "missing"));
        return;
      }
      const target = e.target.closest("[data-select]");
      if (target) select([target.dataset.select]);
    });
    $("#tabs").addEventListener("click", (e) => {
      const button = e.target.closest("button");
      if (!button) return;
      state.doc = button.dataset.doc;
      renderViewer();
    });
    document.addEventListener("keydown", (e) => {
      if (!["j", "k"].includes(e.key) || e.metaKey || e.ctrlKey || e.altKey || /input|textarea|select/i.test(e.target.tagName)) return;
      const rows = [...document.querySelectorAll(".qrow")];
      const at = rows.findIndex((r) => r.dataset.id === state.id);
      const next = rows[Math.max(0, Math.min(rows.length - 1, at + (e.key === "j" ? 1 : -1)))];
      if (next) { selectClaim(next.dataset.id); next.scrollIntoView({ block: "nearest" }); }
    });
  }

  async function init() {
    wire();
    try {
      state.claims = await api("/api/claims");
    } catch (error) {
      $("#claim").innerHTML = `<p class="empty">Claims could not be loaded. Refresh the page. If it keeps failing, the service may be paused.</p>`;
      return;
    }
    renderQueue();
    const first = state.claims.find((c) => c.review_required) || state.claims[0];
    if (first) selectClaim(first.claim_id);
  }

  init();
})();
