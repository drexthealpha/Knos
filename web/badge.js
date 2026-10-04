// The "paid on proof" badge and a payee's record, drawn for the site. Nothing here asks the network for anything: the
// caller hands in what it read (a badge's data, or the record `knos record <login> --json` prints), and gets HTML back.
//
//   badgeSvg(data)          the badge as an SVG string: the same bytes src/knos/badge.py `svg` writes (tests/test_badge.py)
//   renderBadge(el, data)   the badge, linked to the repository's record, with its scope and date in words under it
//   renderRecord(el, rep)   knos_pay's reputation account for a payee, with its caveats in the same view
//
// data: { repo, pr, amount, money, date }  for one pull request, or  { repo, count, other, money, as_of }  for a repository.
// A badge states its scope and its date and never more than the receipt: a count is "as of" a day, test money is
// called test money, and "paid" is an event, not a score of the work.
// rep: { github_id, login, cluster, money, headline: { paid, distinct_funders, total, first, last },
//        apart: { test_paid, test_total, self_paid }, caveats: [...] }

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

export function badgeSvg(d) {
  const msg = badgeMessage(d), a = width(LABEL), b = width(msg);
  const colour = d.money === TEST ? "#57606a" : "#1a7f37";       // test money is grey; green is kept for real money
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${a + b}" height="20" viewBox="0 0 ${a + b} 20" role="img" `
    + `aria-label="${esc(LABEL)}: ${esc(msg)}"><title>${esc(badgeTitle(d))}</title>`
    + `<rect width="${a}" height="20" fill="#24292f"/><rect x="${a}" width="${b}" height="20" fill="${colour}"/>`
    + `<g fill="#fff" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">`
    + `<text x="${a / 2}" y="14" textLength="${a - 12}">${esc(LABEL)}</text>`
    + `<text x="${a + b / 2}" y="14" textLength="${b - 12}">${esc(msg)}</text></g></svg>\n`;
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

export function recordHtml(rep) {
  const h = rep.headline, a = rep.apart, who = rep.login || `GitHub id ${rep.github_id}`;
  const head = Number(h.paid)
    ? `<p class="record-headline"><strong>Paid ${esc(h.paid)} time${s(h.paid)}</strong> by <strong>${esc(h.distinct_funders)} distinct funder${s(h.distinct_funders)}</strong>: ${esc(h.total)} ${esc(rep.money)} in all, first ${esc(h.first)}, last ${esc(h.last)}.</p>`
    : `<p class="record-headline">No payment from someone else is recorded. Nothing recorded is not the same as nothing done.</p>`;
  return `<div class="card paid-record">
    <h3>${esc(who)}</h3>
    <p class="fine">GitHub id ${esc(rep.github_id)}. The record knos_pay keeps on Solana ${esc(rep.cluster)} (the second deployment).</p>
    ${head}
    <h4>Shown apart, not in the count above</h4>
    <dl class="record-apart">
      <dt>In the faucet's test money</dt><dd>${esc(a.test_paid)} payment${s(a.test_paid)}, ${esc(a.test_total)} test USDC</dd>
      <dt>Funded by this account itself</dt><dd>${esc(a.self_paid)} payment${s(a.self_paid)} (the program keeps their number, not their amount)</dd>
    </dl>
    <h4>How to read it</h4>
    <ul class="record-caveats">${(rep.caveats || []).map((c) => `<li>${esc(c)}</li>`).join("")}</ul>
  </div>`;
}

export function renderRecord(el, rep) {
  el.innerHTML = recordHtml(rep);
  return el;
}
