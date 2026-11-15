// Paying an approved statement by bank, in the page: the same file `knos statement pay --rail bank` writes
// (src/knos/rails.py), byte for byte (tests/data/rails, tests/web/rails.mjs). One ISO 20022 customer credit transfer
// initiation (pain.001.001.09) for the lines that are agreed, approved and still payable: one transfer per supplier,
// the settlement id end to end, the invoice line ids and the statement's hash as remittance. Nothing leaves the page:
// the file is made here and saved by the reader, who uploads it to their own bank. No bank has taken such a file yet.
// No dependency: this module imports nothing.

export const MESSAGE = "pain.001.001.09";
export const NS = "urn:iso:std:iso:20022:tech:xsd:" + MESSAGE;
const OK = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/-?:().,'+ ";
const IBAN = /^[A-Z]{2}[0-9]{2}[A-Za-z0-9]{1,30}$/, BIC = /^[A-Z0-9]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$/;
const DAY = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/, WHEN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$/;

// ---- SHA-256, here so the function stays pure and synchronous ----------------------------------------------------------
const K = (() => {
  const out = [], primes = [];
  for (let n = 2; out.length < 64; n++) {
    if (primes.every((p) => n % p)) { primes.push(n); out.push(Math.floor((Math.cbrt(n) % 1) * 4294967296) >>> 0); }
  }
  return out;
})();
export function sha256(bytes) {
  const h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
  const size = bytes.length, total = ((size + 9 + 63) >> 6) << 6, m = new Uint8Array(total), view = new DataView(m.buffer);
  m.set(bytes); m[size] = 0x80;
  view.setUint32(total - 8, Math.floor((size * 8) / 4294967296)); view.setUint32(total - 4, (size * 8) >>> 0);
  const w = new Uint32Array(64), r = (x, n) => (x >>> n) | (x << (32 - n));
  for (let at = 0; at < total; at += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(at + i * 4);
    for (let i = 16; i < 64; i++) {
      const a = w[i - 15], b = w[i - 2];
      w[i] = (w[i - 16] + (r(a, 7) ^ r(a, 18) ^ (a >>> 3)) + w[i - 7] + (r(b, 17) ^ r(b, 19) ^ (b >>> 10))) >>> 0;
    }
    let [a, b, c, d, e, f, g, hh] = h;
    for (let i = 0; i < 64; i++) {
      const t1 = (hh + (r(e, 6) ^ r(e, 11) ^ r(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) >>> 0;
      const t2 = ((r(a, 2) ^ r(a, 13) ^ r(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
      hh = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    [a, b, c, d, e, f, g, hh].forEach((v, i) => { h[i] = (h[i] + v) >>> 0; });
  }
  return h.map((v) => v.toString(16).padStart(8, "0")).join("");
}
const utf8 = (s) => new TextEncoder().encode(s);
const join = (parts) => { const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0)); let at = 0; for (const p of parts) { out.set(p, at); at += p.length; } return out; };
// knos.ids.settlement: "stl_" and 24 hex characters of a SHA-256 over a tagged, length-prefixed list of parts
export function settlementId(...parts) {
  const all = [utf8("knos.id.v1\0settlement\0")];
  for (const p of parts) { const b = utf8(String(p)), n = new Uint8Array(4); new DataView(n.buffer).setUint32(0, b.length); all.push(n, b); }
  return "stl_" + sha256(join(all)).slice(0, 24);
}

// ---- the statement's lines as the status file leaves them (knos.statement.lines_now, the part a payment needs) ------------
export class Refused extends Error {}
const units = (amount, scale) => {
  if (!amount) return 0;
  const neg = amount.startsWith("-"), [whole, part = ""] = amount.replace(/^-/, "").split(".");
  return (neg ? -1 : 1) * Number(whole + part.padEnd(scale, "0").slice(0, scale));
};
const amountOf = (value, scale) => {
  const whole = Math.floor(Math.abs(value) / 10 ** scale), part = String(Math.abs(value) % 10 ** scale).padStart(scale, "0").replace(/0+$/, "");
  return `${value < 0 ? "-" : ""}${whole}.${part.padEnd(2, "0")}`;
};
const cents = (n) => `${Math.floor(n / 100)}.${String(n % 100).padStart(2, "0")}`;
const eventsOf = (st, status) => {
  if (!status) return [];
  if (status.kind !== "knos-statement-status" || status.statement !== st.sha256) throw new Refused("The status file is another statement's: it names another sha256.");
  return status.events;
};

export const text = (value, most) => [...String(value).trim()].map((c) => (OK.includes(c) ? c : ".")).slice(0, most).join("").trim();
export function ibanOk(account) {
  let rest = 0;
  for (const c of (account.slice(4) + account.slice(0, 4)).toUpperCase()) for (const d of String(parseInt(c, 36))) rest = (rest * 10 + Number(d)) % 97;
  return rest === 1;
}
function accountOf(value, whose) {
  const got = String(value || "").replace(/\s+/g, "");
  if (IBAN.test(got) && got.length >= 15) {
    if (!ibanOk(got)) throw new Refused(`${whose}: ${got} looks like an IBAN and its check digits are wrong. Nothing was written.`);
    return ["IBAN", got];
  }
  if (!/^[A-Za-z0-9]{1,34}$/.test(got)) throw new Refused(`${whose}: an account is an IBAN, or up to 34 letters and digits; that is neither.`);
  return ["Othr", got];
}
function bicOf(value, whose) {
  const got = String(value || "").replace(/\s+/g, "").toUpperCase();
  if (got && !BIC.test(got)) throw new Refused(`${whose}: a BIC is 8 or 11 letters and digits; that is not one.`);
  return got;
}

// One transfer per supplier for the lines that are agreed, approved, still payable and in no payment file a bank still holds.
export function transfers(st, status) {
  const events = eventsOf(st, status), sent = new Set();
  for (const e of events) {
    if (e.type === "instruction") for (const t of e.transfers) for (const line of t.lines) sent.add(line);
    else if (e.type === "settlement" && e.returned) sent.delete(e.line);
  }
  const rounds = events.filter((e) => e.type === "instruction").length, by = new Map();
  for (const ln of st.lines) {
    const paid = events.filter((e) => e.type === "settlement" && e.line === ln.invoice_line), payment = paid.length ? paid[paid.length - 1].state : ln.payment;
    const approved = events.some((e) => e.type === "approval" && e.lines.includes(ln.invoice_line));
    if (ln.state === "agreed" && payment === "payable" && approved && ln.amount && !sent.has(ln.invoice_line)) by.set(ln.supplier, [...(by.get(ln.supplier) || []), ln]);
  }
  const cur = String(st.currency);
  if (by.size && !/^[A-Z]{3}$/.test(cur)) throw new Refused(`A bank moves a currency with a three-letter code; ${cur ? `this statement is in '${cur}'` : "this statement states no currency"}. Test money is paid on devnet (--rail usdc), never by bank.`);
  const out = [];
  for (const [supplier, mine] of by) {
    const total = mine.reduce((n, ln) => n + units(ln.amount, st.scale), 0), per = st.scale > 2 ? 10 ** (st.scale - 2) : 1;
    const c = st.scale > 2 ? Math.floor(total / per) : total * 10 ** (2 - st.scale);
    if ((st.scale > 2 && total % per) || total <= 0) throw new Refused(`The lines of ${supplier} come to ${amountOf(total, st.scale)} ${cur}: a bank transfer is a positive amount in whole cents.`);
    const lines = mine.map((ln) => ln.invoice_line);
    out.push({ end_to_end: settlementId(`${st.sha256}:${supplier}`, "bank", lines.join(",") + (rounds ? `#${rounds}` : "")), supplier, amount: cents(c), units: c, currency: cur, lines });
  }
  return out;
}
export const messageId = (st, found) => "KNOS" + sha256(utf8(st.sha256 + "|" + found.map((t) => t.end_to_end).join(","))).slice(0, 28).toUpperCase();

function party(name, [kind, number], agent, who, pad) {
  const inner = kind === "IBAN" ? `<IBAN>${number}</IBAN>` : `<Othr><Id>${number}</Id></Othr>`;
  const out = [`${pad}<${who}><Nm>${name}</Nm></${who}>`, `${pad}<${who}Acct><Id>${inner}</Id></${who}Acct>`];
  const said = `${pad}<${who}Agt><FinInstnId>${agent ? `<BICFI>${agent}</BICFI>` : "<Othr><Id>NOTPROVIDED</Id></Othr>"}</FinInstnId></${who}Agt>`;
  return who === "Dbtr" ? [...out, said] : [...(agent ? [said] : []), ...out];
}

// The payment file's text. `payer`: { name, account, bic, on, execute, created, payees: { supplier: { name, account, bic } } };
// `status`: the statement's status file (or payer.status). The same inputs give the same bytes as the command line's.
export function pain001(statement, payer, status = payer.status || null) {
  const st = statement, found = transfers(st, status);
  if (!found.length) throw new Refused("No line of this statement is agreed, approved and still payable: there is nothing to instruct. `knos statement approve --agreed` approves the agreed lines; a line a bank file already names is not named again.");
  const on = String(payer.on || ""), execute = String(payer.execute || on), created = String(payer.created || `${on}T00:00:00Z`);
  if (!DAY.test(on) || !DAY.test(execute) || !WHEN.test(created)) throw new Refused("A payment file names its day (YYYY-MM-DD), the day to pay and its own time (YYYY-MM-DDThh:mm:ssZ).");
  const name = text(payer.name || "", 140);
  if (!name) throw new Refused("A payment file names who pays: the payer's name.");
  const mine = accountOf(payer.account, "the payer's account"), agent = bicOf(payer.bic, "the payer's bank"), payees = payer.payees || {};
  const missing = found.filter((t) => !(payees[t.supplier] || {}).account).map((t) => t.supplier);
  if (missing.length) throw new Refused(`No bank account is given for ${missing.join(", ")}. The payees file has one row a supplier: supplier,name,account,bic.`);
  const msg = messageId(st, found), summed = cents(found.reduce((n, t) => n + t.units, 0));
  const out = ['<?xml version="1.0" encoding="UTF-8"?>', `<Document xmlns="${NS}">`, "  <CstmrCdtTrfInitn>", "    <GrpHdr>", `      <MsgId>${msg}</MsgId>`,
    `      <CreDtTm>${created}</CreDtTm>`, `      <NbOfTxs>${found.length}</NbOfTxs>`, `      <CtrlSum>${summed}</CtrlSum>`, `      <InitgPty><Nm>${name}</Nm></InitgPty>`,
    "    </GrpHdr>", "    <PmtInf>", `      <PmtInfId>${msg}-1</PmtInfId>`, "      <PmtMtd>TRF</PmtMtd>", `      <NbOfTxs>${found.length}</NbOfTxs>`,
    `      <CtrlSum>${summed}</CtrlSum>`, `      <ReqdExctnDt><Dt>${execute}</Dt></ReqdExctnDt>`, ...party(name, mine, agent, "Dbtr", "      ")];
  for (const t of found) {
    const p = payees[t.supplier], who = text(p.name || t.supplier, 140) || "NOTPROVIDED", said = [text(`KNOS ${st.sha256} INV ${st.invoice}`, 140)];
    for (let n = 0; n < t.lines.length; n += 4) said.push(t.lines.slice(n, n + 4).join(" "));
    out.push("      <CdtTrfTxInf>", `        <PmtId><EndToEndId>${t.end_to_end}</EndToEndId></PmtId>`, `        <Amt><InstdAmt Ccy="${t.currency}">${t.amount}</InstdAmt></Amt>`,
      ...party(who, accountOf(p.account, `the account of ${t.supplier}`), bicOf(p.bic, `the bank of ${t.supplier}`), "Cdtr", "        "),
      "        <RmtInf>", ...said.map((u) => `          <Ustrd>${u}</Ustrd>`), "        </RmtInf>", "      </CdtTrfTxInf>");
  }
  out.push("    </PmtInf>", "  </CstmrCdtTrfInitn>", "</Document>");
  return out.join("\n") + "\n";
}

// ---- the view: a statement and its status in, a payment file out ---------------------------------------------------------
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// `ctx`: { statement, status } to start from (optional), `today` (YYYY-MM-DD, for tests), `files: false` when the page
// that holds this view already has the two files (web/approver.js). The reader drops the statement's
// JSON and its status file, types the paying account and each supplier's, and saves the file. Nothing is sent anywhere.
export function renderRails(el, ctx = {}) {
  let st = ctx.statement || null, status = ctx.status || null;
  const today = ctx.today || new Date().toISOString().slice(0, 10);
  el.innerHTML = `<section class="k-card rails" aria-labelledby="rails-h">
    <p class="k-kicker">Pay by bank</p>
    <h2 id="rails-h">Make the bank's payment file</h2>
    <p>Pays agreed, approved lines only. No bank has tested it.</p>
    <label${ctx.files === false ? " hidden" : ""}>Statement and status files <input type="file" data-rails-files accept=".json,application/json" multiple></label>
    <div data-rails-body></div>
    <p role="status" aria-live="polite" data-rails-said></p>
    <p><a href="https://github.com/drexthealpha/Knos/blob/main/docs/reference/RAILS.md">How the route works</a></p>
  </section>`;
  const body = el.querySelector("[data-rails-body]"), said = el.querySelector("[data-rails-said]");
  const draw = () => {
    if (!st) { body.innerHTML = ""; said.textContent = "Choose a statement."; return; }
    let found = [];
    try { found = transfers(st, status); } catch (e) { body.innerHTML = ""; said.textContent = e.message; return; }
    if (!found.length) { body.innerHTML = ""; said.textContent = "Nothing to pay: no line is agreed, approved and payable."; return; }
    body.innerHTML = `<form data-rails-form>
      <label>Payer name <input name="name" required autocomplete="organization"></label>
      <label>Payer account <input name="account" required placeholder="IBAN" autocomplete="off"></label>
      <div class="k-table-wrap" style="overflow-x:auto"><table class="k-table"><thead><tr><th>Supplier</th><th>Amount</th><th>Lines</th><th>Account</th></tr></thead><tbody>
      ${found.map((t, n) => `<tr><td>${esc(t.supplier)}</td><td class="k-num">${esc(t.amount)} ${esc(t.currency)}</td><td class="k-num">${t.lines.length}</td>
        <td><input name="payee${n}" required aria-label="Account of ${esc(t.supplier)}" placeholder="IBAN" autocomplete="off"></td></tr>`).join("")}
      </tbody></table></div>
      <button type="submit" class="k-btn">Save payment file</button></form>`;
    said.textContent = `${found.length} ${found.length === 1 ? "transfer" : "transfers"} ready.`;
    body.querySelector("form").addEventListener("submit", (ev) => {
      ev.preventDefault();
      const f = new FormData(ev.target), payees = Object.fromEntries(found.map((t, n) => [t.supplier, { name: t.supplier, account: f.get(`payee${n}`) }]));
      try {
        const xml = pain001(st, { name: f.get("name"), account: f.get("account"), on: today, payees }, status);
        el.dataset.railsFile = xml;
        const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([xml], { type: "application/xml" })); a.download = `${messageId(st, found)}.pain001.xml`;
        el.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        said.textContent = "Saved. Upload it to your bank.";
      } catch (e) { said.textContent = e.message; }
    });
  };
  el.querySelector("[data-rails-files]").addEventListener("change", async (ev) => {
    for (const file of ev.target.files) {
      try {
        const doc = JSON.parse(await file.text());
        if (doc.kind === "knos-statement") { st = doc; status = status && status.statement === doc.sha256 ? status : null; }
        else if (doc.kind === "knos-statement-status") status = doc;
      } catch { said.textContent = `${file.name} is not JSON.`; return; }
    }
    draw();
  });
  draw();
  return { open: (statement, stat) => { st = statement; status = stat || null; draw(); } };
}
