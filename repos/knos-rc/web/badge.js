// The "paid on proof" badge and a payee's record, drawn for the site. Nothing here asks the network for anything: the
// caller hands in what it read (a badge's data, or the record `knos record <login> --json` prints), and gets HTML back.
//
//   badgeSvg(data)          the badge as an SVG string: the same bytes src/knos/badge.py `svg` writes (tests/test_badge.py)
//   renderBadge(el, data)   the badge, linked to the repository's record, with its scope and date in words under it
//   renderRecord(el, rep)   knos_pay's reputation account for a payee, with its caveats in the same view. A profile
//                           (accepted work, distinct and repeat funders, disputes and reverts, each with its sample
//                           size) is added only when rep.profile says the account opted in (optIn / readOptIn below);
//                           without it the view is what the chain shows anyway, under the id, and ranks nobody
//
// data: { repo, pr, amount, money, date }  for one pull request, or  { repo, count, other, money, as_of }  for a repository.
// A badge states its scope and its date and never more than the receipt: a count is "as of" a day, test money is
// called test money, and "paid" is an event, not a score of the work.
// rep: { github_id, login, cluster, money, headline: { paid, distinct_funders, total, first, last },
//        apart: { test_paid, test_total, self_paid }, caveats: [...],
//        profile?: { opted_in, source, why }, history?: { repeat_funders, disputes, reverts, of } }

import { BADGE_MARK as MARK } from "./brand/mark.js";      // the Knos mark at the left of a badge (written by scripts/brand.py)

export const SITE = "https://drexthealpha.github.io/Knos";
export const LABEL = "paid on proof";
const TEST = "test USDC";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c]));
const s = (n) => (Number(n) === 1 ? "" : "s");
const width = (text) => Math.round(text.length * 6.4) + 12;      // a fixed width: textLength makes any font fit it

export function badgeMessage(d) {
  if (d.pr) return `#${d.pr}: ${d.amount} ${d.money}, ${d.date}`;
  const n = Number(d.count), other = Number(d.other || 0);
  return `${n} payment${s(n)} in ${d.money}${other ? `, ${other} in another token` : ""}, as of ${d.as_of}`;
}

export function badgeTitle(d) {
  if (d.pr) {
    return `Paid on proof: pull request #${d.pr} of ${d.repo} was paid ${d.amount} ${d.money} on ${d.date} (UTC), after the checks its funder named passed at the merge. This is a payment, not a score of the work.`;
  }
  const n = Number(d.count);
  return `Paid on proof: ${n} payment${s(n)} in ${d.money} for pull requests to ${d.repo}, as of ${d.as_of} (UTC). Each was made after the checks its funder named passed at the merge. This is a count of payments, not a score of the work.`;
}

function draw(label, msg, tip, colour) {
  const m = MARK.width + 7, a = width(label) + m, b = width(msg);      // the mark, 5 from the edge and 2 before the words
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${a + b}" height="20" viewBox="0 0 ${a + b} 20" role="img" `
    + `aria-label="${esc(label)}: ${esc(msg)}"><title>${esc(tip)}</title>`
    + `<rect width="${a}" height="20" fill="#24292f"/><rect x="${a}" width="${b}" height="20" fill="${colour}"/>`
    + `<g fill="#fff" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">`
    + `<path fill-rule="evenodd" transform="${MARK.transform}" d="${MARK.d}"/>`
    + `<text x="${(a + m) / 2}" y="14" textLength="${a - m - 12}">${esc(label)}</text>`
    + `<text x="${a + b / 2}" y="14" textLength="${b - 12}">${esc(msg)}</text></g></svg>\n`;
}

export function badgeSvg(d) {
  return draw(LABEL, badgeMessage(d), badgeTitle(d), d.money === TEST ? "#57606a" : "#1a7f37");      // test money is grey; green is kept for real money
}

// ---- the "Knos-verified" badge -----------------------------------------------------------------------------------------
// v is what src/knos/badge.py `verified(receipt)` returned: { issued, verdict, words, why, digest, pull_request, commit,
// evidence: [{ what, url }], note }. That function runs every rule of the receipt (knos.receipt.check); this file does
// not repeat them. What it does itself: it draws nothing unless v says issued and accepted, and, given the receipt,
// it hashes it again and draws nothing unless the digest is the one v names.
export const VERIFIED_LABEL = "Knos-verified";
export const NOT_FOR_SALE = "This badge is issued only from a receipt that checks. It cannot be bought, and the party it is about never pays for it.";

// The bytes a receipt's digest is taken over: keys sorted, no white space (knos.receipt.canonical).
export function canonical(x) {
  if (Array.isArray(x)) return `[${x.map(canonical).join(",")}]`;
  if (x && typeof x === "object") return `{${Object.keys(x).sort().map((k) => `${JSON.stringify(k)}:${canonical(x[k])}`).join(",")}}`;
  return JSON.stringify(x);
}
export async function receiptDigest(receipt) {
  const h = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(receipt)));
  return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
export const verifiedIssued = (v) => Boolean(v) && v.issued === true && v.verdict === "accepted" && /^[0-9a-f]{64}$/.test(v.digest || "");
export const verifiedMessage = (v) => `${v.pull_request ? `#${v.pull_request}` : String(v.commit || "").slice(0, 12)}: ${v.words}, receipt ${String(v.digest).slice(0, 12)}`;

export function verifiedSvg(v) {
  if (!verifiedIssued(v)) throw new Error(`no badge: ${(v && (v.why || v.words)) || "no receipt that checks"}`);
  const tip = `Knos-verified: the acceptance receipt ${v.digest} checks and its verdict is accepted. It says the agreed checks passed, not that the work is good. ${NOT_FOR_SALE}`;
  return draw(VERIFIED_LABEL, verifiedMessage(v), tip, "#1a7f37");
}

// ---- a supplier's record as a badge (src/knos/record_page.py `badge_data`, `badge_svg`: the same strings, the same bytes) ----
// From the record file alone. With work settled through Knos it is "Knos-verified" and counts it; without, it says so
// and gives the public row. The sample is always stated. Green only with accepted work settled through Knos.
export const RECORD_LABEL = "Knos record";
export const RECORD_RULE = "The supplier never pays for this record and cannot pay to change it.";
export const RECORD_NOT_A_SCORE = "Counts with their samples. Nothing here is a score.";
export function recordBadge(doc) {
  const o = doc.orders, p = doc.public, c = Object.fromEntries(Object.entries(o.counts).map(([k, v]) => [k, v.n]));
  let label = RECORD_LABEL, message = `nothing on record, as of ${doc.as_of}`;
  if (o.sample) {
    label = VERIFIED_LABEL;
    message = `${c.accepted} accepted, ${c.reverted} reverted, sample ${o.sample}${o.period.from ? `, ${o.period.from} to ${o.period.to}` : `, as of ${doc.as_of}`}`;
  } else if (p && p.sample) message = `no Knos orders yet; public PRs: ${p.failed_at_merge} of ${p.sample} had a failed check, week of ${p.week}`;
  return { label, message, title: `${label}: ${doc.name}. ${message}. ${RECORD_NOT_A_SCORE} ${RECORD_RULE}`, colour: o.sample && c.accepted ? "#1a7f37" : "#57606a" };
}
export function recordBadgeSvg(doc) {
  const b = recordBadge(doc);
  return draw(b.label, b.message, b.title, b.colour);
}
export const recordBadgeMarkdown = (doc, image) => { const b = recordBadge(doc); return `[![${b.label}: ${b.message}](${image})](${doc.links.page})`; };

// The badge with its evidence under it, or one line saying why there is none. `receipt` (optional): hashed again here.
export async function renderVerified(el, v, receipt = null) {
  const same = !receipt || (verifiedIssued(v) && await receiptDigest(receipt) === v.digest);
  if (!verifiedIssued(v) || !same) {
    const why = !same ? "the receipt does not hash to the digest the badge names" : (v && (v.why || v.words)) || "no receipt that checks";
    el.innerHTML = `<p class="fine" data-verified="no">No badge: ${esc(why)}.</p>`;
    return el;
  }
  const links = (v.evidence || []).filter((e) => /^https:\/\//.test(e.url)).map((e) => `<a href="${esc(e.url)}">${esc(e.what)}</a>`).join(", ");
  el.innerHTML = `<span class="paid-badge" data-verified="yes">${verifiedSvg(v).trim()}</span>
    <p class="fine">Receipt <code>${esc(v.digest)}</code>. ${links ? `Evidence: ${links}. ` : ""}${esc(NOT_FOR_SALE)}</p>`;
  return el;
}

// The repository's record on the site: every payment for it, each with its transaction.
export const receiptUrl = (repo) => `${SITE}/r/${String(repo).split("/").map(encodeURIComponent).join("/")}.html`;

export function badgeHtml(d) {
  const scope = d.pr ? `One pull request: #${esc(d.pr)} of ${esc(d.repo)}, paid on ${esc(d.date)} (UTC).`
    : `Every payment for pull requests to ${esc(d.repo)}, as of ${esc(d.as_of)} (UTC). A later payment is not in it.`;
  return `<a class="paid-badge" href="${esc(receiptUrl(d.repo))}">${badgeSvg(d).trim()}</a>
    <p class="fine">${scope} ${d.money === TEST ? "Test USDC on Solana devnet: not money. " : ""}The badge says a payment was made after the funder's named checks passed at the merge; the record it links to has each transaction. It says nothing else about the work.</p>`;
}

export function renderBadge(el, data) {
  el.innerHTML = badgeHtml(data);
  return el;
}

// ---- opt-in profiles ---------------------------------------------------------------------------------------------------
// The program's record of a payee is public: anyone can read it from the chain by GitHub id. A PROFILE (a name over it,
// accepted work, repeat funders, disputes and reverts) is shown only when the account asked for one, by keeping the
// file .knos/profile.json with {"public_record": true} in the public repository named after itself (<login>/<login>).
// There is no comment command for this (src/knos/commands.py has none): the file is the whole convention. Deleting
// the file, or setting false, takes the profile down at the next read. Nobody is ranked in either view.
export const PROFILE_FILE = ".knos/profile.json";
const part = (x) => encodeURIComponent(String(x));
export const profileRepo = (login) => `${login}/${login}`;
export const profileUrl = (login) => `https://api.github.com/repos/${part(login)}/${part(login)}/contents/${PROFILE_FILE}`;

// What a profile file says. `file`: the parsed file, or what GitHub's contents API answers for it ({ content, encoding }),
// or null when it is not there. Opted in only on a literal `true`; a file that names another account does not count.
export function optIn(file, login, githubId) {
  const no = (why) => ({ opted_in: false, why, source: `${profileRepo(login)}/${PROFILE_FILE}` });
  if (file == null) return no("the file is not there");
  let said = file;
  if (typeof file.content === "string" && file.encoding === "base64") {
    try { said = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(file.content.replace(/\s/g, "")), (c) => c.charCodeAt(0)))); } catch { return no("the file is not JSON"); }
  }
  if (typeof said !== "object" || said === null || Array.isArray(said)) return no("the file is not a JSON object");
  if (said.public_record !== true) return no('the file does not say "public_record": true');
  if (said.github_id != null && githubId != null && Number(said.github_id) !== Number(githubId)) return no("the file names another account id");
  return { opted_in: true, source: `${profileRepo(login)}/${PROFILE_FILE}` };
}

// Ask for the file with the caller's own reader: `get(url)` resolves to the parsed answer, or null when GitHub says the
// file is not there. This module still asks the network for nothing itself. A reader that fails is "not opted in".
export async function readOptIn(login, get, githubId) {
  if (!login) return { opted_in: false, why: "no login is known for this id", source: PROFILE_FILE };
  try { return optIn(await get(profileUrl(login)), login, githubId); } catch { return { ...optIn(null, login), why: "GitHub did not answer for the file" }; }
}

const SMALL = 30;        // under this many, a count is shown with a warning that it says little
const sample = (n, what) => `<span class="record-sample">sample: ${esc(n)} ${what}${Number(n) < SMALL ? "; too few to say much" : ""}</span>`;

// The four lines of a profile, each with the number of payments it is taken over. rep.history is optional: what the
// caller counted from the site's history of events ({ repeat_funders, disputes, reverts, of }); the program's record of
// a payee keeps none of the three, and without it the lines say so and show no number.
function profileHtml(rep) {
  const h = rep.headline, n = Number(h.paid), hist = rep.history || null, again = Math.max(0, n - Number(h.distinct_funders));
  const repeat = hist && hist.repeat_funders != null
    ? `${esc(hist.repeat_funders)} of ${esc(h.distinct_funders)} funder${s(h.distinct_funders)} paid more than once ${sample(h.distinct_funders, `distinct funder${s(h.distinct_funders)}`)}`
    : `${esc(again)} of ${esc(n)} payment${s(n)} came from a funder who had paid this account before (the program keeps how many funders, not which came back) ${sample(n, `payment${s(n)}`)}`;
  const trouble = hist && hist.disputes != null && hist.reverts != null
    ? `${esc(hist.disputes)} dispute${s(hist.disputes)} and ${esc(hist.reverts)} revert${s(hist.reverts)} ${sample(hist.of ?? n, `accepted payment${s(hist.of ?? n)} in the site's history`)}`
    : `not counted: the program's record of a payee keeps no count of disputes or reverts ${sample(0, "read")}`;
  return `<h4>Profile</h4>
    <p class="fine">Shown because this account opted in: ${esc(rep.profile.source)} says "public_record": true. Removing the file takes this section down.</p>
    <dl class="record-profile">
      <dt>Accepted work</dt><dd>${esc(n)} payment${s(n)} from someone else, each made after the funder's named checks passed ${sample(n, `payment${s(n)}`)}</dd>
      <dt>Distinct funders</dt><dd>${esc(h.distinct_funders)} ${sample(n, `payment${s(n)}`)}</dd>
      <dt>Repeat funders</dt><dd>${repeat}</dd>
      <dt>Disputes and reverts</dt><dd>${trouble}</dd>
    </dl>`;
}

export function recordHtml(rep) {
  const h = rep.headline, a = rep.apart, opted = !!(rep.profile && rep.profile.opted_in === true);
  const who = opted && rep.login ? rep.login : `GitHub id ${rep.github_id}`;      // without a profile the chain's own name for it: the id
  const head = Number(h.paid)
    ? `<p class="record-headline"><strong>Paid ${esc(h.paid)} time${s(h.paid)}</strong> by <strong>${esc(h.distinct_funders)} distinct funder${s(h.distinct_funders)}</strong>: ${esc(h.total)} ${esc(rep.money)} in all, first ${esc(h.first)}, last ${esc(h.last)}.</p>`
    : `<p class="record-headline">No payment from someone else is recorded. Nothing recorded is not the same as nothing done.</p>`;
  const demo = rep.cluster === "devnet"
    ? `<p class="record-demo"><strong>Devnet demonstration.</strong> Every amount here is test USDC on Solana devnet: it shows how a record reads, and is not a record of money earned.</p>` : "";
  const scope = opted ? "" : ` Anyone can read this from the chain, so it is shown as it stands: no profile, no place in any list. This account has not opted in to a profile${rep.profile && rep.profile.why ? ` (${esc(rep.profile.why)})` : ""}.`;
  const how = opted ? "" : `<p class="fine record-optin">To show a profile here (accepted work, repeat funders, disputes and reverts), the account adds the file <code>${esc(PROFILE_FILE)}</code> with <code>{"public_record": true}</code> to its public repository named after itself${rep.login ? ` (<code>${esc(profileRepo(rep.login))}</code>)` : ""}.</p>`;
  return `<div class="card paid-record" data-profile="${opted ? "opted-in" : "chain-only"}">
    ${demo}
    <h3>${esc(who)}</h3>
    <p class="fine">GitHub id ${esc(rep.github_id)}. The record knos_pay keeps on Solana ${esc(rep.cluster)} (the second deployment).${scope}</p>
    ${head}
    <h4>Shown apart, not in the count above</h4>
    <dl class="record-apart">
      <dt>In the faucet's test money</dt><dd>${esc(a.test_paid)} payment${s(a.test_paid)}, ${esc(a.test_total)} test USDC</dd>
      <dt>Funded by this account itself</dt><dd>${esc(a.self_paid)} payment${s(a.self_paid)} (the program keeps their number, not their amount)</dd>
    </dl>
    ${opted ? profileHtml(rep) : ""}
    <h4>How to read it</h4>
    <ul class="record-caveats">${(rep.caveats || []).map((c) => `<li>${esc(c)}</li>`).join("")}</ul>
    ${how}
  </div>`;
}

export function renderRecord(el, rep) {
  el.innerHTML = recordHtml(rep);
  return el;
}
