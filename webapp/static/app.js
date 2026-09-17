/* Quotation Studio UI.
 *
 * This file builds a form and displays what the server returns. It performs no
 * arithmetic of its own -- there is not a single `+` on a money value below.
 * Every figure shown is a preformatted string from the engine, and every
 * refusal is the engine's own, pinned to the field it named.
 */

const $ = (id) => document.getElementById(id);
let SCHEMA = null;
let LAST_PDF = null;

/* The page has two modes. They share the party cards and the terms card; every
 * other card declares which mode it belongs to with data-mode. There is no
 * stage control anywhere below, in either mode, because there is no stage
 * input in the engine -- it is derived from the ageing and only displayed. */
let MODE = "document";
let EXAMPLES = [];

/* The original document behind a proforma reminder, when an example carried
 * one. Held as opaque state and posted back untouched: the engine recomputes
 * the amount from it, and the browser must not be the thing that edits it. */
let SOURCE_DOC = null;

/* ---------- small helpers ---------- */

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, "");
    else if (v !== false && v != null) node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(kid));
  }
  return node;
}

function stateOptions(select, selected) {
  select.replaceChildren(
    el("option", { value: "" }, "-- select --"),
    ...SCHEMA.states.map((s) =>
      el("option", { value: s.code, selected: s.code === selected },
         `${s.name} (${s.code})`)));
}

/* ---------- the registration gate ---------- */

const gate = { registered: true, composition: false, reverse_charge: false };

function buildGate() {
  $("gate").replaceChildren(...SCHEMA.registration_questions.map((q) => {
    const yes = el("button", { type: "button" }, "Yes");
    const no = el("button", { type: "button" }, "No");
    const paint = () => {
      yes.className = gate[q.key] ? "on" : "";
      no.className = gate[q.key] ? "" : "on";
    };
    yes.onclick = () => { gate[q.key] = true; paint(); recompute(); };
    no.onclick = () => { gate[q.key] = false; paint(); recompute(); };
    paint();
    return el("div", { class: "q" },
      el("p", {}, q.question),
      el("span", { class: "toggle" }, no, yes));
  }));
}

/* ---------- line items ---------- */

function itemRow(data = {}) {
  const tr = el("tr");
  const mk = (id, ph, cls, val) =>
    el("input", { class: cls || "", placeholder: ph, value: val ?? "",
                  "data-k": id, oninput: recompute });

  const rate = el("select", { "data-k": "gst_rate", onchange: recompute },
    ...SCHEMA.common_rates.map((r) =>
      el("option", { value: r, selected: String(data.gst_rate ?? "18") === r },
         `${r}%`)));

  tr.append(
    el("td", {}, mk("description", "What you are supplying", "", data.description)),
    el("td", {}, mk("hsn_sac", "998314", "", data.hsn_sac)),
    el("td", {}, mk("quantity", "1", "num", data.quantity ?? "1")),
    el("td", {}, mk("rate", "0.00", "num", data.rate)),
    el("td", {}, mk("discount_value", "0", "num",
        data.discount_kind === "percent" ? data.discount_value : "")),
    el("td", {}, rate),
    el("td", {}, el("button", {
      class: "x", type: "button", title: "Remove line",
      onclick: () => { tr.remove(); recompute(); },
    }, "×")));
  return tr;
}

function readItems() {
  return [...$("items").querySelectorAll("tr")].map((tr) => {
    const get = (k) => tr.querySelector(`[data-k="${k}"]`)?.value.trim() ?? "";
    const disc = get("discount_value");
    const item = {
      description: get("description"),
      hsn_sac: get("hsn_sac"),
      quantity: get("quantity") || "1",
      rate: get("rate"),
      gst_rate: get("gst_rate"),
    };
    if (disc && disc !== "0") {
      item.discount_kind = "percent";
      item.discount_value = disc;
    }
    return item;
  });
}

/* ---------- place of supply ---------- */

function buildNature(selected) {
  $("nature_label").textContent = SCHEMA.nature_question;
  $("nature").replaceChildren(...SCHEMA.natures.map((n) =>
    el("option", { value: n.value, selected: n.value === selected }, n.label)));
  $("nature").onchange = () => { syncFollowUp(); recompute(); };
  syncFollowUp();
}

function syncFollowUp(preset) {
  const nature = SCHEMA.natures.find((n) => n.value === $("nature").value);
  const spec = nature?.follow_up;
  $("follow_up_wrap").hidden = !spec;
  if (!spec) return;
  $("follow_up_label").textContent = spec.question;
  $("follow_up").dataset.field = spec.field;
  if (!$("follow_up").options.length || preset !== undefined) {
    stateOptions($("follow_up"), preset ?? $("follow_up").value);
  }
  $("follow_up").onchange = recompute;
}

/* ---------- assembling the payload ---------- */

function payload() {
  const lines = (s) => s.split("\n").map((x) => x.trim()).filter(Boolean);
  const pos = { nature: $("nature").value };
  if (!$("follow_up_wrap").hidden) {
    pos[$("follow_up").dataset.field] = $("follow_up").value;
  }
  return {
    doc_type: $("doc_type").value,
    number: $("number").value.trim(),
    issue_date: $("issue_date").value,
    valid_until: $("valid_until").value || null,
    registration: { ...gate },
    supplier: {
      name: $("s_name").value.trim(),
      gstin: $("s_gstin").value.trim() || null,
      state_code: $("s_state").value,
      address: lines($("s_address").value),
    },
    client: {
      name: $("c_name").value.trim(),
      gstin: $("c_gstin").value.trim() || null,
      state_code: $("c_state").value,
      address: lines($("c_address").value),
    },
    place_of_supply: pos,
    items: readItems(),
    terms: lines($("terms").value),
    upi_id: $("upi_id").value.trim() || null,
  };
}

/* ---------- payments received ---------- */

function paymentRow(data = {}) {
  const tr = el("tr");
  const mk = (id, ph, cls, val, type) =>
    el("input", { class: cls || "", placeholder: ph, value: val ?? "",
                  type: type || "text", "data-k": id, oninput: recompute });

  tr.append(
    el("td", {}, mk("received_on", "", "", data.received_on, "date")),
    el("td", {}, mk("amount", "0.00", "num", data.amount)),
    el("td", {}, mk("method", "NEFT", "", data.method)),
    el("td", {}, mk("reference", "UTR / cheque no", "", data.reference)),
    el("td", {}, el("button", {
      class: "x", type: "button", title: "Remove payment",
      onclick: () => { tr.remove(); recompute(); },
    }, "×")));
  return tr;
}

function readPayments() {
  return [...$("payments").querySelectorAll("tr")].map((tr) => {
    const get = (k) => tr.querySelector(`[data-k="${k}"]`)?.value.trim() ?? "";
    const row = { received_on: get("received_on"), amount: get("amount") };
    if (get("method")) row.method = get("method");
    if (get("reference")) row.reference = get("reference");
    return row;
  }).filter((r) => r.received_on || r.amount);
}

/* ---------- assembling a reminder ---------- */

function reminderPayload() {
  const lines = (s) => s.split("\n").map((x) => x.trim()).filter(Boolean);
  const buckets = $("r_buckets").value
    .split(",").map((x) => x.trim()).filter(Boolean);

  const body = {
    number: $("r_number").value.trim(),
    as_of: $("r_as_of").value,
    reference: {
      kind: $("r_kind").value,
      number: $("r_ref_number").value.trim(),
      dated: $("r_ref_dated").value,
    },
    supplier: {
      name: $("s_name").value.trim(),
      gstin: $("s_gstin").value.trim() || null,
      state_code: $("s_state").value,
      address: lines($("s_address").value),
    },
    client: {
      name: $("c_name").value.trim(),
      gstin: $("c_gstin").value.trim() || null,
      state_code: $("c_state").value,
      address: lines($("c_address").value),
    },
    payments: readPayments(),
    history: lines($("r_history").value),
    terms: lines($("terms").value),
    notes: $("r_notes").value.trim() || null,
    upi_id: $("upi_id").value.trim() || null,
  };

  // The amount is only sent when no original document is attached. With one,
  // the engine recomputes the total from it, and a figure typed here could
  // only ever contradict that.
  if (SOURCE_DOC) body.source_document = SOURCE_DOC;
  else if ($("r_amount").value.trim()) {
    body.reference.amount = $("r_amount").value.trim();
  }

  if ($("r_credit_days").value.trim()) {
    body.credit_days = $("r_credit_days").value.trim();
  }
  if ($("r_due_date").value) body.due_date = $("r_due_date").value;
  if (buckets.length) body.ageing_buckets = buckets;

  if ($("r_interest_on").checked) {
    body.interest = {
      rate_percent_per_annum: $("r_rate").value.trim(),
      declared_in: $("r_declared_in").value.trim(),
      day_count_basis: $("r_day_count").value,
      basis: $("r_basis").value,
    };
  }
  return body;
}

function currentPayload() {
  return MODE === "reminder" ? reminderPayload() : payload();
}

function loadReminder(data) {
  $("r_number").value = data.number ?? "";
  $("r_as_of").value = data.as_of ?? "";

  const ref = data.reference ?? {};
  $("r_kind").value = ref.kind ?? "invoice";
  $("r_ref_number").value = ref.number ?? "";
  $("r_ref_dated").value = ref.dated ?? "";
  $("r_amount").value = ref.amount ?? "";

  SOURCE_DOC = data.source_document ?? null;
  syncAttached();
  syncKindHint();

  $("r_credit_days").value = data.credit_days ?? "";
  $("r_due_date").value = data.due_date ?? "";
  $("r_buckets").value = (data.ageing_buckets ?? SCHEMA.reminder.default_buckets)
    .join(", ");

  const party = (p, prefix) => {
    $(`${prefix}_name`).value = p?.name ?? "";
    $(`${prefix}_gstin`).value = p?.gstin ?? "";
    stateOptions($(`${prefix}_state`), p?.state_code ?? "");
    $(`${prefix}_address`).value = (p?.address ?? []).join("\n");
  };
  party(data.supplier, "s");
  party(data.client, "c");

  $("payments").replaceChildren(...(data.payments ?? []).map(paymentRow));

  const interest = data.interest ?? null;
  $("r_interest_on").checked = Boolean(interest);
  if (interest) {
    $("r_rate").value = interest.rate_percent_per_annum ?? "";
    $("r_declared_in").value = interest.declared_in ?? "";
    $("r_day_count").value = String(interest.day_count_basis ?? "365");
    if (interest.basis) $("r_basis").value = interest.basis;
  }
  syncInterest();

  $("r_history").value = (data.history ?? []).join("\n");
  $("terms").value = (data.terms ?? []).join("\n");
  $("r_notes").value = data.notes ?? "";
  $("upi_id").value = data.upi_id ?? "";

  checkGstin("s");
  checkGstin("c");
  recompute();
}

function syncAttached() {
  const on = Boolean(SOURCE_DOC);
  $("r_attached").hidden = !on;
  $("f_r_amount").hidden = on;
  if (on) {
    $("r_attached_text").textContent =
      `Original document attached (${SOURCE_DOC.number ?? "?"}) — the engine ` +
      `recomputes its total rather than trusting a figure typed here.`;
  }
}

function syncKindHint() {
  const kind = SCHEMA.reminder.reference_kinds
    .find((k) => k.value === $("r_kind").value);
  $("r_kind_hint").textContent = kind?.provenance ?? "";
}

function syncInterest() {
  $("r_interest_fields").hidden = !$("r_interest_on").checked;
}

function load(data) {
  $("doc_type").value = data.doc_type ?? "quotation";
  syncDisclaimer();
  $("number").value = data.number ?? "";
  $("issue_date").value = data.issue_date ?? "";
  $("valid_until").value = data.valid_until ?? "";

  Object.assign(gate, { registered: true, composition: false,
                        reverse_charge: false }, data.registration ?? {});
  buildGate();

  const party = (p, prefix) => {
    $(`${prefix}_name`).value = p?.name ?? "";
    $(`${prefix}_gstin`).value = p?.gstin ?? "";
    stateOptions($(`${prefix}_state`), p?.state_code ?? "");
    $(`${prefix}_address`).value = (p?.address ?? []).join("\n");
  };
  party(data.supplier, "s");
  party(data.client, "c");

  const pos = data.place_of_supply ?? { nature: "general_service" };
  buildNature(pos.nature);
  const spec = SCHEMA.natures.find((n) => n.value === pos.nature)?.follow_up;
  if (spec) syncFollowUp(pos[spec.field] ?? "");

  $("items").replaceChildren(...(data.items ?? []).map(itemRow));
  $("terms").value = (data.terms ?? []).join("\n");
  $("upi_id").value = data.upi_id ?? "";

  checkGstin("s");
  checkGstin("c");
  recompute();
}

/* ---------- live GSTIN validation ---------- */

async function checkGstin(prefix) {
  const input = $(`${prefix}_gstin`);
  const hint = $(`${prefix}_gstin_hint`);
  const field = $(`f_${prefix}_gstin`);
  const value = input.value.trim();

  if (!value) {
    hint.textContent = "";
    hint.className = "hint";
    field.classList.remove("bad");
    return;
  }
  const res = await fetch(`/api/gstin?value=${encodeURIComponent(value)}`);
  const v = await res.json();
  if (v.state === "valid") {
    field.classList.remove("bad");
    hint.className = "hint ok";
    hint.textContent =
      `checksum ok · ${v.state_name} · ${v.entity_type}`;
  } else {
    field.classList.add("bad");
    hint.className = "hint err";
    hint.textContent = v.reason;
  }
}

/* ---------- rendering the verdict ---------- */

let pending = null;

function recompute() {
  clearTimeout(pending);
  pending = setTimeout(async () => {
    document.body.classList.add("busy");
    try {
      const url = MODE === "reminder" ? "/api/reminder/compute" : "/api/compute";
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentPayload()),
      });
      const data = await res.json();
      if (!data.ok) showRefusal(data.refusal);
      else if (MODE === "reminder") showReminderResult(data);
      else showResult(data);
    } finally {
      document.body.classList.remove("busy");
    }
  }, 180);
}

function showRefusal(r) {
  $("verdict_card").hidden = true;
  $("rem_verdict_card").hidden = true;
  $("checks_card").hidden = true;
  $("warn_slot").replaceChildren();
  markFields(r.findings);

  $("refusal_slot").replaceChildren(el("div", { class: "refusal" },
    el("h3", {}, r.fatal ? "Internal check failed" : "Refused"),
    el("div", { class: "msg", style: "margin-bottom:6px" }, r.summary),
    ...r.findings.map((f) => el("div", { class: "f" },
      f.field ? el("div", { class: "fld" }, f.field) : null,
      el("div", { class: "msg" }, f.message),
      el("div", { class: "rid" }, f.rule_id))),
    el("div", { class: "none" }, "No document was produced.")));
}

const FIELD_MAP = {
  "supplier.gstin": "f_s_gstin", "client.gstin": "f_c_gstin",
  "supplier.state_code": "s_state", "client.state_code": "c_state",
  "supplier.name": "s_name", "client.name": "c_name",
  "number": "number", "issue_date": "issue_date", "valid_until": "valid_until",
};

/* The same map for reminder mode. Kept separate rather than merged, because
 * "number" means two different inputs depending on which form is on screen. */
const REMINDER_FIELD_MAP = {
  "number": "r_number", "as_of": "r_as_of",
  "reference.number": "r_ref_number", "reference.dated": "r_ref_dated",
  "reference.amount": "r_amount", "reference.kind": "r_kind",
  "credit_days": "r_credit_days", "due_date": "r_due_date",
  "ageing_buckets": "r_buckets", "history": "r_history",
  "interest": "r_rate",
  "interest.rate_percent_per_annum": "r_rate",
  "interest.declared_in": "r_declared_in",
  "interest.day_count_basis": "r_day_count",
  "supplier.gstin": "f_s_gstin", "client.gstin": "f_c_gstin",
  "supplier.state_code": "s_state", "client.state_code": "c_state",
  "supplier.name": "s_name", "client.name": "c_name",
  "client": "c_name", "supplier": "s_name", "payments": "payments",
  "source_document": "r_attached",
};

function markFields(findings) {
  // Clear last pass, except fields whose own live validator is still unhappy.
  document.querySelectorAll(".field.bad").forEach((n) => {
    if (!n.querySelector(".hint.err")) n.classList.remove("bad");
  });
  document.querySelectorAll("input.bad-input, select.bad-input")
    .forEach((n) => n.classList.remove("bad-input"));

  const map = MODE === "reminder" ? REMINDER_FIELD_MAP : FIELD_MAP;

  for (const f of findings) {
    const target = $(map[f.field]);
    if (target) (target.closest(".field") ?? target).classList.add("bad");

    // items[n].field in document mode, payments[n].field in reminder mode.
    const m = f.field.match(/^(items|payments|history)\[(\d+)\](?:\.(\w+))?$/);
    if (!m) continue;
    if (m[1] === "history") {
      $("r_history").closest(".field")?.classList.add("bad");
      continue;
    }
    const tr = $(m[1]).querySelectorAll("tr")[Number(m[2])];
    const cell = m[3] ? tr?.querySelector(`[data-k="${m[3]}"]`)
                      : tr?.querySelector("input");
    if (cell) {
      cell.classList.add("bad-input");
      cell.title = f.message;
    }
  }
}

function showResult(d) {
  $("refusal_slot").replaceChildren();
  markFields([]);
  $("verdict_card").hidden = false;
  $("rem_verdict_card").hidden = true;
  $("checks_card").hidden = false;
  $("dates_adv").hidden = true;

  const split = $("split");
  split.textContent = d.tax.charged
    ? `${d.tax.split}  —  ${d.tax.interstate ? "inter-state" : "intra-state"}`
    : "No tax charged";
  split.className = "split " + (!d.tax.charged ? "none"
    : d.tax.interstate ? "inter" : "intra");

  $("pos").replaceChildren(
    "Place of supply: ", el("b", {}, d.place_of_supply.state),
    el("span", { class: "rule-chip" }, d.place_of_supply.rule));
  $("why").textContent = d.tax.charged
    ? d.place_of_supply.reasoning
    : `${d.place_of_supply.reasoning}  Tax is not charged because ${d.tax.why_not}.`;

  const rows = [["Subtotal", d.totals.gross]];
  if (d.totals.discount !== "0.00") rows.push(["Discount", d.totals.discount]);
  rows.push(["Taxable value", d.totals.taxable]);
  if (d.tax.charged) {
    if (d.tax.interstate) rows.push(["IGST", d.totals.igst]);
    else { rows.push(["CGST", d.totals.cgst]); rows.push(["SGST", d.totals.sgst]); }
  }
  if (d.totals.round_off !== "0.00") rows.push(["Rounding", d.totals.round_off]);

  $("totals").replaceChildren(
    ...rows.map(([k, v]) => el("tr", {}, el("td", {}, k), el("td", {}, v))),
    el("tr", { class: "grand" },
      el("td", {}, "Total payable"), el("td", {}, d.totals.grand)));

  $("words").textContent = d.totals.words;
  $("manifest").textContent = d.manifest;

  showWarnings(d.warnings);

  $("checks").replaceChildren(...d.checks_run.map((c) => el("li", {}, c)));
  $("facts").replaceChildren(...d.facts.map((f) => el("tr", {},
    el("td", {}, f.key), el("td", {}, f.value), el("td", {}, f.formula))));
  $("scope").textContent = SCHEMA.scope_note;
}

function showWarnings(warnings) {
  $("warn_slot").replaceChildren(warnings.length
    ? el("div", { class: "warns" },
        el("h3", {}, `${warnings.length} warning${warnings.length > 1 ? "s" : ""}`),
        ...warnings.map((w) => el("div", { class: "w" },
          el("b", {}, w.field), " — ", w.message)))
    : el("div"));
}

function showReminderResult(d) {
  $("refusal_slot").replaceChildren();
  markFields([]);
  $("verdict_card").hidden = true;
  $("rem_verdict_card").hidden = false;
  $("checks_card").hidden = false;
  $("dates_adv").hidden = false;

  const overdue = d.ageing.days_overdue > 0;
  const status = $("r_status");
  status.textContent = `${d.ageing.status}  —  ${d.ageing.bucket}`;
  status.className = "split " + (overdue ? "overdue" : "due");

  // The stage is shown, never offered. The engine derived it; the browser is
  // only allowed to say which one came back and why.
  $("r_stage").replaceChildren(
    d.doc.title, el("span", { class: "rule-chip" }, `stage: ${d.doc.stage}`),
    el("span", { class: "rule-chip" }, "derived, not chosen"));
  $("r_stage_why").textContent = `${d.doc.stage_why}. ${d.ageing.bucket_why}.`;

  const dates = [
    ["Reference", `${d.reference.label} ${d.reference.number}, dated ${d.reference.dated}`],
    ["Due", `${d.ageing.due_date}  (${d.ageing.derivation})`],
    ["Position as at", d.ageing.as_of],
    ["Amount taken from", d.reference.amount_source],
  ];
  $("r_dates").replaceChildren(...dates.map(([k, v]) =>
    el("tr", {}, el("td", {}, k), el("td", {}, v))));

  const rows = [[`${d.reference.label} amount`, d.totals.amount_due]];
  if (d.totals.payments !== "0.00") {
    rows.push(["Less payments received", d.totals.payments]);
  }
  rows.push(["Balance outstanding", d.totals.outstanding]);
  if (d.totals.charges_interest) rows.push(["Interest", d.totals.interest]);

  $("r_totals").replaceChildren(
    ...rows.map(([k, v]) => el("tr", {}, el("td", {}, k), el("td", {}, v))),
    el("tr", { class: "grand" },
      el("td", {}, d.totals.grand_label), el("td", {}, d.totals.grand)));

  $("r_words").textContent = d.totals.words;
  $("r_manifest").textContent = d.manifest;

  showWarnings(d.warnings);
  $("checks").replaceChildren(...d.checks_run.map((c) => el("li", {}, c)));
  $("date_facts").replaceChildren(...d.date_facts.map((f) => el("tr", {},
    el("td", {}, f.key), el("td", {}, f.value), el("td", {}, f.formula))));
  $("facts").replaceChildren(...d.facts.map((f) => el("tr", {},
    el("td", {}, f.key), el("td", {}, f.value), el("td", {}, f.formula))));
  $("scope").textContent = SCHEMA.reminder.scope_note;
}

/* ---------- switching modes ---------- */

function setMode(mode, { push = true } = {}) {
  MODE = mode;

  // Keep the mode in the URL, so /?mode=reminder opens straight on the
  // reminder form and a reload stays where you were.
  if (push) {
    const url = new URL(location.href);
    if (mode === "document") url.searchParams.delete("mode");
    else url.searchParams.set("mode", mode);
    history.replaceState(null, "", url);
  }

  document.querySelectorAll("#mode button").forEach((b) => {
    b.className = b.dataset.mode === mode ? "on" : "";
  });
  document.querySelectorAll("[data-mode]").forEach((n) => {
    if (n.closest("#mode")) return;
    n.hidden = n.dataset.mode !== mode;
  });

  const reminder = mode === "reminder";
  $("claim").textContent = reminder
    ? "Date and balance correctness — nothing about whether it is owed"
    : "Arithmetic and field correctness — nothing about tax law";
  $("out_title").textContent = reminder ? "Reminder" : "Document";
  $("render").textContent = reminder ? "Render reminder" : "Render PDF";
  $("env").innerHTML = SCHEMA.typst.available
    ? `rulepack ${reminder ? SCHEMA.reminder.rulepack : SCHEMA.rulepack} &middot; typst <b>ready</b>`
    : `rulepack ${reminder ? SCHEMA.reminder.rulepack : SCHEMA.rulepack} &middot; typst <b class="off">missing</b>`;

  $("verdict_card").hidden = true;
  $("rem_verdict_card").hidden = true;
  $("checks_card").hidden = true;
  $("refusal_slot").replaceChildren();
  $("warn_slot").replaceChildren();
  $("pdf").hidden = true;
  $("download").disabled = true;
  $("render_status").textContent = "";
  LAST_PDF = null;

  buildExamples();
  const first = EXAMPLES.find((ex) => ex.kind === mode);
  if (first) (reminder ? loadReminder : load)(first.payload);
  else recompute();
}

/* ---------- render ---------- */

async function renderPdf() {
  const btn = $("render");
  btn.disabled = true;
  $("render_status").textContent = "rendering…";
  try {
    const url = MODE === "reminder" ? "/api/reminder/render" : "/api/render";
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentPayload()),
    });
    const data = await res.json();
    if (!data.ok) {
      showRefusal(data.refusal);
      $("pdf").hidden = true;
      $("render_status").textContent = "refused — nothing written";
      return;
    }
    if (MODE === "reminder") showReminderResult(data);
    else showResult(data);
    LAST_PDF = data;
    $("pdf").src = `data:application/pdf;base64,${data.pdf_base64}`;
    $("pdf").hidden = false;
    $("download").disabled = false;
    $("render_status").textContent = "verified against the rendered PDF";
  } finally {
    btn.disabled = false;
  }
}

function download() {
  if (!LAST_PDF) return;
  const a = el("a", {
    href: `data:application/pdf;base64,${LAST_PDF.pdf_base64}`,
    download: LAST_PDF.filename,
  });
  document.body.append(a);
  a.click();
  a.remove();
}

/* ---------- boot ---------- */

function syncDisclaimer() {
  const d = SCHEMA.doc_types.find((t) => t.value === $("doc_type").value);
  $("doc_disclaimer").textContent = d?.disclaimer ?? "";
}

function buildExamples() {
  const mine = EXAMPLES.filter((ex) => ex.kind === MODE);
  $("examples").replaceChildren(...mine.map((ex, i) =>
    el("button", {
      class: "action" + (i === 0 ? " primary" : ""),
      onclick: () => (MODE === "reminder" ? loadReminder : load)(ex.payload),
    }, ex.name)));
}

async function boot() {
  SCHEMA = await (await fetch("/api/schema")).json();

  $("doc_type").replaceChildren(...SCHEMA.doc_types.map((t) =>
    el("option", { value: t.value }, t.title)));
  $("doc_type").onchange = () => { syncDisclaimer(); recompute(); };

  $("r_kind").replaceChildren(...SCHEMA.reminder.reference_kinds.map((k) =>
    el("option", { value: k.value }, k.label)));
  $("r_kind").onchange = () => { syncKindHint(); recompute(); };

  $("r_basis").replaceChildren(...SCHEMA.reminder.interest_bases.map((b) =>
    el("option", { value: b.value }, b.description)));

  for (const id of ["number", "issue_date", "valid_until", "s_name",
                    "s_address", "c_name", "c_address", "terms", "upi_id",
                    "r_number", "r_as_of", "r_ref_number", "r_ref_dated",
                    "r_amount", "r_credit_days", "r_due_date", "r_buckets",
                    "r_rate", "r_declared_in", "r_history", "r_notes"]) {
    $(id).addEventListener("input", recompute);
  }
  for (const id of ["r_day_count", "r_basis"]) {
    $(id).addEventListener("change", recompute);
  }
  for (const p of ["s", "c"]) {
    $(`${p}_gstin`).addEventListener("input", () => {
      checkGstin(p);
      recompute();
    });
    $(`${p}_state`).addEventListener("change", recompute);
  }

  $("r_interest_on").onchange = () => { syncInterest(); recompute(); };
  $("r_detach").onclick = () => {
    SOURCE_DOC = null;
    syncAttached();
    recompute();
  };

  $("add_item").onclick = () => {
    $("items").append(itemRow({ gst_rate: "18" }));
    recompute();
  };
  $("add_payment").onclick = () => {
    $("payments").append(paymentRow());
    recompute();
  };
  $("render").onclick = renderPdf;
  $("download").onclick = download;

  document.querySelectorAll("#mode button").forEach((b) => {
    b.onclick = () => setMode(b.dataset.mode);
  });

  EXAMPLES = (await (await fetch("/api/examples")).json()).examples;

  const wanted = new URL(location.href).searchParams.get("mode");
  setMode(wanted === "reminder" ? "reminder" : "document", { push: false });
}

boot();
