// Records and ranks: what Knos has paid and to whom, read from the static JSON files scripts/pages_data.py writes beside
// this page (records.json, u/<login>.json, r/<owner>/<repo>.json, rank/<name>.json, badge/...). Same origin, no other
// request: each page says which file it read, from what source and when it was generated, as the file itself says.
// A person with no file gets a sentence, never a made-up zero.
import { show } from "./price.js";
import { renderBadge, renderRecord, readOptIn } from "./badge.js";
import { cache as kept, fileKey, asOf } from "./cache.js";

export const KIND_WORDS = { real: "real USDC", test: "test USDC", self: "paid to the funder's own account", own: "Knos's own accounts" };
export const RANKS = { earners: "Earners", funders: "Funders", agents: "Agents by false-claim rate" };

const LOGIN = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?$/;
const REPO = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[\w.-]{1,100}$/;

export const stamp = (iso) => (iso ? `${String(iso).slice(0, 16).replace("T", " ")} UTC` : "none yet");
const percent = (x) => `${(x * 100).toFixed(1)}%`;
// "40.0% (4 of 10; 95% interval 16.7%-68.8%)", as pages_data.py words a rate; "n/a" when there is nothing to count
export const rateWords = (r) => (!r || r.share === null || r.share === undefined ? "n/a" : `${percent(r.share)} (${r.k} of ${r.n}; 95% interval ${percent(r.ci95[0])}-${percent(r.ci95[1])})`);
export const seconds = (s) => (s === null || s === undefined ? "n/a" : s < 120 ? `${s} s` : s < 7200 ? `${(s / 60).toFixed(1)} min` : `${(s / 3600).toFixed(1)} h`);

// What the lookup box was given, as the hash it leads to: a login, a repository, or a link to either on GitHub; null for anything else.
export function lookup(text) {
  const t = String(text || "").trim().replace(/^(?:https?:\/\/)?(?:www\.)?github\.com\//, "").replace(/^@/, "").replace(/[?#].*$/, "").replace(/\/+$/, "").replace(/\.git$/, "");
  const parts = t.split("/");
  if (parts.length === 1 && LOGIN.test(t)) return `#u=${encodeURIComponent(t)}`;
  if (parts.length >= 2 && REPO.test(parts.slice(0, 2).join("/"))) return `#r=${parts[0]}/${parts[1]}`;
  return null;
}

// a file of the site, read now: its parsed JSON, or null when the site has none (a 404); anything else is an error with a sentence
export async function readFile(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`The site's file ${path} did not load (${r.status}).`);
  try { return await r.json(); } catch { throw new Error(`The site's file ${path} is not JSON.`); }
}
// the same, read once for as long as the page is open (the lists and statements, which do not change under a reader)
const cache = new Map();
export async function jsonFile(path) {
  if (cache.has(path)) return cache.get(path);
  const data = await readFile(path);
  if (data !== null) cache.set(path, data);
  return data;
}
const sharedTable = (esc, head, rows) => (rows.length ? `<div class="table-wrap"><table><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : `<p class="fine">Nothing to show yet.</p>`);
const sharedSource = (esc, data, path, id = "rec-source") => `<p class="fine" id="${id}">Read from <a href="${esc(path)}">${esc(path)}</a>, made ${esc(stamp(data.generated))} from ${esc(data.source?.summary || "a source the file does not name")}.</p>`;
export const isLogin = (x) => LOGIN.test(x);
export const tableHtml = sharedTable, sourceHtml = sharedSource;

// What web/badge.js draws, from what this page read. Both are worded as src/knos/badge.py words them.
// The record: knos_pay's reputation account of a payee (sdk/settle readRep), as badge.py `record_view` shapes it.
const CAVEATS = ["Paid is an event: a funder's named checks passed at a merge and the program paid. It is not a score of the work.",
  "Distinct funders counts different funders. Ten payments from one funder add one.",
  "Payments in the faucet's test money and payments an account funded itself are shown apart and are not in the headline.",
  "Solana devnet: every amount here is test USDC, not money."];
const amount = (units) => show(units).replace(/,/g, ""), day = (t) => new Date(t * 1000).toISOString().slice(0, 10);
export const recordView = (rep, githubId, login) => ({ github_id: githubId, login, cluster: "devnet", money: "test USDC",
  headline: { paid: rep.paid, distinct_funders: rep.funders, total: amount(rep.total), first: rep.paid && rep.first ? day(rep.first) : null, last: rep.paid && rep.last ? day(rep.last) : null },
  apart: { test_paid: rep.testPaid, test_total: amount(rep.testTotal), self_paid: rep.selfPaid }, caveats: CAVEATS });
// The badge of a repository: its payments in test money, with the ones in another token named apart, as of the day the
// file was made. A payment to the funder's own account or to one of Knos's own accounts is in neither count.
export const badgeData = (rec) => ({ repo: rec.repository, count: rec.as_earner?.amounts?.test?.count ?? 0, other: rec.as_earner?.amounts?.real?.count ?? 0,
  money: "test USDC", as_of: String(rec.generated || "").slice(0, 10) });

export function initRecords(ctx) {
  const { $, esc } = ctx;
  const say = (html, kind = "") => { $("rec-result").innerHTML = `<p class="status ${kind}">${html}</p>`; };
  const file = jsonFile;
  const table = (head, rows) => sharedTable(esc, head, rows);
  const kinds = (amounts, columns) => table(["kind of money", ...columns], Object.keys(KIND_WORDS).map((k) => [esc(KIND_WORDS[k]), esc(amounts?.[k]?.count ?? 0), esc(show(amounts?.[k]?.amount ?? 0))]));
  const sourceLine = (data, path) => sharedSource(esc, data, path);
  const unpaid = (items, empty) => (items === null || items === undefined ? `<p class="fine">Not measured: GitHub was not asked or did not answer.</p>`
    : items.length ? table(["repository", "issue", "pull request", "merged", "refunded"], items.map((i) => [esc(i.repository), esc(i.issue), esc(i.pull_request), esc(stamp(i.merged_at)), esc(stamp(i.refunded_at))])) : `<p>${esc(empty)}</p>`);

  function badgeView(b) {
    if (!b || typeof b.label !== "string" || typeof b.message !== "string") return "";
    const color = /^[a-z]+$/.test(String(b.color)) ? b.color : "lightgrey";
    return `<span class="badge" id="rec-badge" role="img" aria-label="${esc(b.label)}: ${esc(b.message)}" data-color="${esc(color)}"><span class="badge-label">${esc(b.label)}</span><span class="badge-message">${esc(b.message)}</span></span>`;
  }

  // A record is shown twice (cache.js): at once from what this tab read before, with its age, then from the files and
  // devnet as they are now. A record seen before is on the page before any request is answered.
  async function record(kind, asked) {
    say(`Reading records.json…`);
    try { await kept.twice((read, pass) => draw(kind, asked, (path) => read(fileKey(path), () => readFile(path)), pass)); }
    catch (e) {
      const note = $("rec-asof");
      if (!Number.isFinite(e?.kept) || !note) { $("rec-result").removeAttribute("data-kept"); throw e; }      // nothing of it is on the page: the sentence is the caller's
      note.textContent = `Shown ${asOf(e.kept, kept.now())}. It could not be read again just now: ${e.message}`;
    }
  }

  async function draw(kind, asked, file, pass) {
    const noun = kind === "u" ? "account" : "repository";
    // records.json says who has a file: asking it first means no request for a file the site does not have
    const index = await file("records.json").catch((e) => { if (pass.kept) throw e; return null; }), list = index ? (kind === "u" ? index.accounts : index.repositories) : null;
    const name = list ? list.find((x) => x.toLowerCase() === asked.toLowerCase()) : asked, path = `${kind}/${name}.json`;
    const rec = name ? await file(path) : null, badge = rec ? await file(`badge/${path}`).catch((e) => { if (pass.kept) throw e; return null; }) : null;
    $("rec-result").toggleAttribute("data-kept", pass.kept);      // set while what is shown is what was kept, gone once the files have been read again
    if (pass.same()) { $("rec-asof")?.remove(); return chainRecord(rec, kind, pass); }      // what is on the page is what the files say now
    if (!rec) {
      say(`No record for ${esc(asked)}. Only an ${esc(noun)} that was paid or funded a task, and that GitHub named, has one${list ? `: this site has ${list.length} ${noun === "account" ? "accounts" : "repositories"} with a record` : ""}${index?.unnamed_accounts ? ` and ${index.unnamed_accounts} accounts GitHub did not name` : ""}.
        Nothing here means nothing was recorded, not that nothing was paid. <a href="#records">Everyone with a record</a>.`);
      return;
    }
    const e = rec.as_earner, f = rec.as_funder, title = rec.login || rec.repository;
    const gh = `https://github.com/${title}`;
    $("rec-result").innerHTML = `<div class="card" id="rec-card" data-kind="${esc(kind)}">
      <h3>${esc(title)}</h3>
      <p class="fine">${esc(noun)}, GitHub id ${esc(rec.github_id)}; <a href="${esc(gh)}" target="_blank" rel="noopener">on GitHub</a>.</p>
      ${sourceLine(rec, path)}
      <h4>${kind === "u" ? "Paid as the person who did the work" : "Paid for work in this repository"}</h4>
      <p id="rec-earned">${esc(e.paid_merges)} paid; first ${esc(stamp(e.first))}, last ${esc(stamp(e.last))}. ${esc(e.distinct_funders)} distinct funders (${esc(e.distinct_funders_real)} with real USDC)${kind === "r" ? `, ${esc(e.payees)} people paid` : ""}.
        Refusals at merge: ${esc(e.refusals_at_merge === null ? "not measured" : e.refusals_at_merge)}.</p>
      ${kinds(e.amounts, ["payments", "USDC received"])}
      <h4>As funder</h4>
      ${kinds(f.funded, ["funded", "USDC funded"])}${kinds(f.paid, ["paid", "USDC paid"])}${kinds(f.refunded, ["refunded", "USDC refunded"])}
      <p id="rec-funder">Open now: ${esc(f.open)}. Of the real-USDC jobs that ended, ${esc(rateWords(f.reliability))} ended in payment. Median time from a pull request passing its checks to the merge or rejection:
        ${esc(f.review?.seconds?.n ? seconds(f.review.seconds.p50) : (f.review?.note || "not measured"))} over ${esc(f.review?.seconds?.n ?? 0)} pull requests.</p>
      <h4>Merged but unpaid</h4>
      <p class="fine">A pull request that closes a funded issue was merged, and the bounty was refunded instead. This says both happened, not whose fault it was.</p>
      ${unpaid(f.merged_unpaid, "None: no pull request that closed a funded issue was merged and then refunded.")}
      ${kind === "u" && rec.merged_but_unpaid_to_me ? `<h4>Merged but unpaid, as the author</h4>${unpaid(rec.merged_but_unpaid_to_me, "None.")}` : ""}
      ${kind === "r" ? `<h4>Paid on proof</h4><div id="rec-paid"></div>` : `<h4>The record on Solana</h4><div id="rec-chain"><p class="fine">Reading Solana devnet…</p></div>`}
      <h4>README badge</h4>
      <p>${badgeView(badge) || `<span class="fine">The badge file for this record is not there.</span>`}</p>
      <p class="fine">Paste this line into a README. The badge is drawn by shields.io from <a href="${esc(`badge/${path}`)}">${esc(`badge/${path}`)}</a>; the picture above is drawn by this page from the same file, so nothing is asked of shields.io here.</p>
      <pre id="rec-readme">${esc(rec.badge?.readme || "")}</pre>
      <p><button type="button" id="rec-copy" class="ghost small">Copy the line</button> <a href="${esc(`${path.replace(/\.json$/, "")}.html`)}">The same record as a page to share</a>${kind === "u" ? ` <a id="rec-statement" href="#statement=${encodeURIComponent(title)}">Statements by month, with a CSV</a>` : ""}</p>
    </div>`;
    const copy = $("rec-copy");
    copy.onclick = async () => { try { await navigator.clipboard.writeText(rec.badge?.readme || ""); copy.textContent = "Copied"; } catch { copy.textContent = "Select the line and copy it by hand"; } };
    if (kind === "r") {
      renderBadge($("rec-paid"), badgeData(rec));
      $("rec-paid").insertAdjacentHTML("beforeend", `<p class="fine">Counted from ${esc(path)}: payments by someone else in the faucet's test money. A payment to the funder's own account, or to one of Knos's own accounts, is not in the badge.</p>`);
    }
    if (pass.kept) $("rec-card").insertAdjacentHTML("afterbegin", `<p class="fine" id="rec-asof">Shown ${esc(asOf(pass.at(), kept.now()))}. Reading it again…</p>`);
    chainRecord(rec, kind, pass);
  }

  // the program's own account for this GitHub id: what was kept is shown with its age, then it is read from devnet, and said when it cannot be
  function chainRecord(rec, kind, pass) {
    const box = $("rec-chain");
    if (!rec || kind !== "u" || !box) return;
    if (!ctx.rep) { box.innerHTML = ""; return; }
    const key = `rep:${rec.github_id}`, had = pass.peek(key), asked = pass.peek(`profile:${rec.github_id}`);
    const show = (rep, at, profile) => {
      renderRecord(box, { ...recordView(rep, rec.github_id, rec.login), profile });
      if (at !== null) box.insertAdjacentHTML("beforeend", `<p class="fine" id="rec-chain-asof">Read from Solana devnet ${esc(asOf(at, kept.now()))}. Reading it again…</p>`);
    };
    if (had && pass.kept) show(had.value, had.at, asked?.value);
    if (pass.kept) return;
    Promise.all([ctx.rep(rec.github_id), profileOf(rec, asked)]).then(([rep, profile]) => { kept.set(key, rep); if (box.isConnected) show(rep, null, profile); },
      () => {
        if (!box.isConnected) return;
        if (box.querySelector("#rec-chain-asof")) box.querySelector("#rec-chain-asof").textContent = `Solana devnet did not answer just now. This is the program's record as it was read ${asOf(had.at, kept.now())}.`;
        else box.innerHTML = `<p class="fine">Solana devnet did not answer just now, so the program's own record is not shown. The numbers above are from the site's file.</p>`;
      });
  }

  // Whether the account asked for a profile over its record: its own file on GitHub (web/badge.js, readOptIn). One read of
  // GitHub's public API, kept for ten minutes of this tab, so that looking at records does not use up the 60 reads an hour
  // a reader with no login has. An answer GitHub did not give is not kept, and is said as that, never as "not opted in".
  const PROFILE_FOR = 10 * 60 * 1000;
  async function profileOf(rec, asked) {
    if (asked && kept.now() - asked.at < PROFILE_FOR) return asked.value;
    const get = ctx.get || ((u) => fetch(u, { headers: { Accept: "application/vnd.github+json" } }).then((r) => { if (r.ok) return r.json(); if (r.status === 404) return null; throw new Error(`GitHub said ${r.status}`); }));
    const profile = await readOptIn(rec.login, get, rec.github_id);
    if (profile.why !== "GitHub did not answer for the file") kept.set(`profile:${rec.github_id}`, profile);
    return profile;
  }

  const who = (login, id) => (login ? `<a href="#u=${encodeURIComponent(login)}">${esc(login)}</a>` : esc(`id ${id}`));
  async function rank(name) {
    const path = `rank/${name}.json`;
    say(`Reading ${esc(path)}…`);
    const r = await file(path);
    if (!r) { say(`This site has no ${esc(path)} yet.`); return; }
    const rows = {
      earners: () => table(["rank", "account", "USDC received", "paid merges", "distinct funders", "first", "last"], r.entries.map((x) => [esc(x.rank), who(x.login, x.github_id), esc(show(x.paid_amount)), esc(x.paid_merges), esc(x.distinct_funders), esc(stamp(x.first)), esc(stamp(x.last))])),
      funders: () => table(["rank", "funder", "USDC paid out", "paid", "refunded", "open", "reliability (paid of paid + refunded)", "merged but unpaid"],
        r.entries.map((x) => [esc(x.rank), x.github_id ? who(x.login, x.github_id) : esc(x.funder), esc(show(x.paid_amount)), esc(x.paid_jobs), esc(x.refunded_jobs), esc(x.open_jobs), esc(rateWords(x.reliability)), esc(x.merged_unpaid === null ? "not measured" : x.merged_unpaid)])),
      agents: () => table(["rank", "agent", "repositories", "a check had failed", "95% interval", "a test or build check failed", "95% interval"],
        r.entries.map((x) => [esc(x.rank), esc(x.name), esc(x.repositories), esc(x.false_claim_rate === null ? "n/a" : percent(x.false_claim_rate)), esc(x.ci95 ? `${percent(x.ci95[0])}-${percent(x.ci95[1])}` : "n/a"),
          esc(x.test_or_build_rate === null ? "n/a" : percent(x.test_or_build_rate)), esc(x.test_or_build_ci95 ? `${percent(x.test_or_build_ci95[0])}-${percent(x.test_or_build_ci95[1])}` : "n/a")])),
    }[name]();
    const note = name === "agents"
      ? (r.note || `Of the repositories where the agent's first pull request said tests or CI pass, the share where a check had failed at the head commit (Agent PR Index of ${r.date}, pull requests created ${r.window?.[0]} to ${r.window?.[1]}). A failed check is GitHub's record, not a judgment of why.`)
      : `Real USDC only. Test money, a payment to the funder's own account and Knos's own accounts are not counted${name === "funders" ? " in a rank" : ""}: ${Object.entries(r.left_out || {}).map(([k, v]) => `${v} ${k}`).join(", ")} payments left out.`;
    $("rec-result").innerHTML = `<div class="card" id="rec-rank" data-rank="${esc(name)}"><h3>${esc(RANKS[name])}${name === "agents" && r.month ? `, ${esc(r.month)}` : ""}</h3><p>${esc(note)}</p>${rows}${sourceLine(r, path)}</div>`;
  }

  async function index() {
    const box = $("rec-index");
    try {
      const r = await file("records.json");
      if (!r) { box.innerHTML = `<p class="fine">This site has no records.json yet, so there is no one to list.</p>`; return; }
      const list = (items, hash) => (items.length ? `<ul class="inline">${items.map((x) => `<li><a href="#${hash}=${x.split("/").map(encodeURIComponent).join("/")}">${esc(x)}</a></li>`).join("")}</ul>` : `<p class="fine">None yet.</p>`);
      box.innerHTML = `<h4>Accounts with a record (${r.accounts.length})</h4>${list(r.accounts, "u")}<h4>Repositories with a record (${r.repositories.length})</h4>${list(r.repositories, "r")}
        <p class="fine">No file, unnamed by GitHub: ${esc(r.unnamed_accounts || 0)} accounts, ${esc(r.unnamed_repositories)} repositories.</p><details class="k-more"><summary>Why</summary><p class="fine">${esc(r.note)}.</p></details>${sharedSource(esc, r, "records.json", "rec-index-source")}`;
    } catch (e) { box.innerHTML = `<p class="status bad">${esc(e.message)}</p>`; }
  }

  $("rec-form").onsubmit = (ev) => {
    ev.preventDefault();
    const to = lookup($("rec-q").value);
    if (!to) return say("Enter a GitHub login, or a repository as owner/name, or a link to either.", "bad");
    if (location.hash === to) route(); else location.hash = to;
  };
  let route = () => {};

  // the view, for a hash of #records, #u=login, #r=owner/repo or #rank=name
  return async function showRecords(kind, arg) {
    route = () => showRecords(kind, arg);
    try {
      if (kind === "u" && LOGIN.test(arg)) { $("rec-q").value = arg; await record("u", arg); }
      else if (kind === "r" && REPO.test(arg)) { $("rec-q").value = arg; await record("r", arg); }
      else if (kind === "rank" && RANKS[arg]) await rank(arg);
      else if (kind === "records") $("rec-result").innerHTML = "";
      else say(kind === "rank" ? `There is no rank called ${esc(arg)}. The ranks are earners, funders and agents.` : `${esc(arg)} is not a GitHub login or an owner/name repository.`, "bad");
    } catch (e) { say(esc(e.message), "bad"); }
    await index();
  };
}
