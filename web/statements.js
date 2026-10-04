// Statements: what an account was paid, or paid out, in one month, as a table and a CSV built in this browser.
// Read from statements/<login>.json (scripts/pages_data.py): one row per payment, in the mint's six decimals. The months,
// the table and the totals are worked out here from those rows; nothing is asked of anyone but this site, and the CSV is
// made from the rows on screen, in the browser, not fetched.
import { jsonFile, tableHtml, sourceHtml, isLogin, KIND_WORDS } from "./records.js";
import { show } from "./price.js";

const ROLES = { seller: ["as_seller", "Seller: what the account was paid"], owner: ["as_owner", "Owner: what the account's money paid out"] };
const KINDS = Object.keys(KIND_WORDS);

// months with at least one payment, newest first
export const monthsOf = (rows) => [...new Set(rows.map((r) => r.month))].sort().reverse();
export const inMonth = (rows, month) => rows.filter((r) => r.month === month);

// the totals of the rows given, by what each payment is counted as: real, test, self, own are never added together
export function totals(rows) {
  const out = {};
  for (const r of rows) {
    const t = (out[r.kind] ||= { kind: r.kind, currency: r.currency, payments: 0, amount_units: 0, fee_units: 0, total_units: 0 });
    t.payments++; t.amount_units += r.amount_units; t.fee_units += r.fee_units; t.total_units += r.total_units;
  }
  return KINDS.filter((k) => out[k]).map((k) => out[k]);
}

// A spreadsheet runs a cell that starts with = + - @ as a formula: text from GitHub gets a quote in front of one
// (as src/knos/records.py does for its receipts). Fields with a comma, quote or line break are quoted, as RFC 4180 says.
const safe = (v) => { const t = v === null || v === undefined ? "" : String(v); return typeof v === "string" && /^[=+\-@\t\r]/.test(t) ? `'${t}` : t; };
const field = (v) => { const t = safe(v); return /[",\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
export const csvOf = (columns, rows) => `${columns.join(",")}\n${rows.map((r) => columns.map((c) => field(r[c])).join(",")).join("\n")}${rows.length ? "\n" : ""}`;

export function initStatements(ctx) {
  const { $, esc, EXPLORER } = ctx;
  let loaded = null;           // { login, file }
  const say = (html, kind = "") => { $("stm-result").innerHTML = `<p class="status ${kind}">${html}</p>`; };
  const rolesRows = () => loaded.file[ROLES[$("stm-role").value][0]] || [];

  function months() {
    const have = monthsOf(rolesRows()), box = $("stm-month");
    box.innerHTML = have.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("");
    box.disabled = !have.length;
  }

  function render() {
    const rows = rolesRows(), month = $("stm-month").value, role = $("stm-role").value, login = loaded.login;
    if (!rows.length) { say(`${esc(login)} has no payment as ${role === "seller" ? "a seller" : "an owner"} in this site's files. ${role === "seller" ? "Try owner" : "Try seller"}.`); return; }
    const mine = inMonth(rows, month), seller = role === "seller", other = seller ? "funder" : "payee";
    const repo = (r) => (r.repository && /^[\w.-]+\/[\w.-]+$/.test(r.repository) ? `<a href="https://github.com/${esc(r.repository)}/issues/${esc(r.issue)}" target="_blank" rel="noopener">${esc(r.repository)}#${esc(r.issue)}</a>` : esc(`repository ${r.repository_id}, issue #${r.issue}`));
    const tx = (r) => (/^[1-9A-HJ-NP-Za-km-z]{60,90}$/.test(r.transaction || "") ? `<a href="${esc(EXPLORER("tx", r.transaction))}" target="_blank" rel="noopener">${esc(r.transaction.slice(0, 8))}…</a>` : esc(r.transaction || ""));
    const sum = totals(mine).map((t) => [esc(`${KIND_WORDS[t.kind]}`), esc(t.payments), esc(show(t.amount_units)), esc(show(t.fee_units)), esc(show(t.total_units)), esc(t.currency)]);
    $("stm-result").innerHTML = `<div id="stm-statement" data-role="${esc(role)}" data-month="${esc(month)}">
      <h4>${esc(login)}, ${esc(month)}: ${seller ? "paid to this account" : "paid out by this account"}</h4>
      <p class="fine">UTC days of the month, from the escrows' log lines on Solana devnet as the file lists them. ${seller ? "Amount is what reached the account; fee is what the escrow kept; total is what left escrow." : "Amount is what reached the people who did the work; fee is what the escrow kept; total is what left escrow."}</p>
      <div id="stm-table-box">${tableHtml(esc, ["date", "task", "pull request", other, "amount", "fee", "total", "currency", "transaction"], mine.map((r) => [esc(r.date), repo(r), esc(r.pull_request ?? ""), esc(seller ? r.funder ?? "" : r.payee ?? `id ${r.payee_id}`),
        esc(show(r.amount_units)), esc(show(r.fee_units)), esc(show(r.total_units)), esc(r.currency + (r.kind === "self" || r.kind === "own" ? ` (${KIND_WORDS[r.kind]})` : "")), tx(r)]))}</div>
      <h4>Totals</h4>
      <div id="stm-totals">${tableHtml(esc, ["counted as", "payments", seller ? "received" : "to the payees", "fees", "total out of escrow", "currency"], sum)}</div>
      <p><button type="button" id="stm-csv" class="ghost small"${mine.length ? "" : " disabled"}>Download the CSV</button> <span class="fine">Made here, from these rows, in your browser.</span></p>
      ${sourceHtml(esc, loaded.file, `statements/${loaded.login}.json`, "stm-source")}</div>`;
    const csv = $("stm-csv");
    csv.onclick = () => {
      const blob = new Blob([csvOf(loaded.file.columns, mine)], { type: "text/csv;charset=utf-8" }), url = URL.createObjectURL(blob), a = document.createElement("a");
      a.href = url; a.download = `knos-statement-${login}-${role}-${month}.csv`;
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    };
  }

  async function open(asked) {
    if (!isLogin(asked)) return say("Enter a GitHub login: letters, digits and single hyphens.", "bad");
    say(`Reading records.json…`);
    try {
      const index = await jsonFile("records.json").catch(() => null);
      const login = index ? index.accounts.find((x) => x.toLowerCase() === asked.toLowerCase()) : asked;
      const file = login ? await jsonFile(`statements/${login}.json`) : null;
      if (!file) { loaded = null; $("stm-month").innerHTML = ""; $("stm-month").disabled = true; say(`This site has no statement file for ${esc(asked)}. Only an account that was paid or funded a task, and that GitHub named, has one. <a href="#records">Everyone with a record</a>.`); return; }
      loaded = { login, file };
      $("stm-login").value = login;
      if (!(file.as_seller || []).length && (file.as_owner || []).length) $("stm-role").value = "owner";
      months();
      render();
    } catch (e) { say(esc(e.message), "bad"); }
  }

  $("stm-role").innerHTML = Object.entries(ROLES).map(([k, [, words]]) => `<option value="${k}">${esc(words)}</option>`).join("");
  $("stm-form").onsubmit = (ev) => { ev.preventDefault(); open($("stm-login").value.trim().replace(/^@/, "")); };
  $("stm-role").onchange = () => { if (loaded) { months(); render(); } };
  $("stm-month").onchange = () => { if (loaded) render(); };
  return (login) => { if (login) { $("stm-login").value = login; open(login); } $("statements").scrollIntoView?.(); };
}
