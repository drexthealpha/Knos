// Share a check: the result of #check (web/check.js) as a link, a line of text, a post and a picture, and a badge for
// the repository's README. Nothing is posted, sent or stored by this file: "Post on X" opens X's own compose box with
// the words filled in, and the reader decides. The only request it makes is the one that decides whether a badge is
// offered (below), to GitHub's public API, with no token, and only when the reader opens it.
//
// THE VERDICT is what web/check.js `readPr` answers for one pull request, the detail of its "knos:check" event:
//   { ref: { owner, repo, number },           the pull request the reader pasted
//     url, claim: { phrase, line } | null,    the sentence of the description that says the tests pass, as written
//     cls,                                    the index's class of the head commit (failed, passed, pending, no-ci, ...)
//     split: { test: [names], other: [names] },  failed checks: test, build, lint or type; and the rest
//     line,                                   the verdict in one line, as #check shows it
//     merged, merged_at? }                    merged_at (GitHub's) spares the badge its one read when it is recent
// THE LINK carries the pull request: #check=owner/repo/123 opens #check and checks it again for whoever opens it, from
// GitHub as it is then (readShareHash; #check=owner/repo, without a number, is the badge's link: the check for that
// repository's pull requests). A crawler that draws a link preview runs no script, so a shared link previews as the
// site's own card (og:image, brand/card.png), not this verdict: the PNG below is the picture to attach.
//
// THE BADGE is a static file of the site, brand/checked.svg (the bytes of checkedBadgeSvg, held equal by
// tests/test_share.py). It is offered only for a repository that merged a pull request in the last 30 days.
import { SITE } from "./badge.js";
import { BADGE_MARK } from "./brand/mark.js";
import { CARD } from "./brand/card.js";

export const CLASSES = ["test", "other"];
export const CLASS_WORDS = { test: "test, build, lint or type", other: "other" };
export const POST = "https://x.com/intent/tweet";        // X's post web intent (docs.x.com, x-for-websites/post-button/guides/web-intent)
export const POST_LIMIT = 280, LINK_LENGTH = 23;         // X counts every link as 23 characters (t.co)
export const BADGE_FILE = "brand/checked.svg";
export const BADGE_LABEL = "agent PR claims", BADGE_MESSAGE = "checked by Knos";
export const ACTIVE_DAYS = 30;
const API = "https://api.github.com";

const escHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const OWNER = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/, REPO = /^[\w.-]{1,100}$/;
const named = (owner, repo) => OWNER.test(owner) && REPO.test(repo) && repo !== "." && repo !== "..";

// ---- the link ---------------------------------------------------------------------------------------------------------
/** { owner, repo, number } from "#check=owner/repo/123", { owner, repo } from "#check=owner/repo", else null. */
export function readShareHash(hash) {
  let h = String(hash ?? "");
  try { h = decodeURIComponent(h); } catch { return null; }
  const m = /^#?check=([^/]+)\/([^/]+)(?:\/(\d{1,9}))?\/?$/.exec(h);
  if (!m || !named(m[1], m[2]) || (m[3] && Number(m[3]) < 1)) return null;
  return m[3] ? { owner: m[1], repo: m[2], number: Number(m[3]) } : { owner: m[1], repo: m[2] };
}
export const shareHash = (pr) => `#check=${pr.owner}/${pr.repo}${pr.number ? `/${pr.number}` : ""}`;
export const shareUrl = (pr, base = SITE) => `${base}/${shareHash(pr)}`;
export const prLabel = (pr) => `${pr.owner}/${pr.repo}#${pr.number}`;

// ---- the words ----------------------------------------------------------------------------------------------------------
/** Failed checks by class: { test, other } (web/check_rules.js `byClass`). */
export const counts = (v) => Object.fromEntries(CLASSES.map((c) => [c, Array.isArray(v?.split?.[c]) ? v.split[c].length : 0]));
const total = (c) => CLASSES.reduce((n, k) => n + c[k], 0);
export const claimOf = (v) => String(v?.claim?.line || v?.claim?.phrase || "").replace(/\s+/g, " ").trim();
const clip = (s, n) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);

export function claimLine(v, n = 140) {
  const said = claimOf(v);
  return said ? `Claimed: “${clip(said, n)}”` : "Claimed nothing about tests.";
}

export function countsLine(v) {
  const c = counts(v);
  return total(c) ? `Failed checks: ${CLASSES.map((k) => `${c[k]} ${CLASS_WORDS[k]}`).join("; ")}.` : "No check failed.";
}

/** The colour of the verdict, as #check colours it: bad when a claim meets a failed check, ok when every check passed. */
export const tone = (v) => (v?.cls === "failed" && v?.claim ? "bad" : v?.cls === "passed" ? "ok" : "ink");

/** What "Copy the result" puts on the clipboard. */
export const resultText = (v, base = SITE) => [`${prLabel(v.ref)}: ${v.line}`, claimLine(v, 200), countsLine(v), `${BADGE_MESSAGE}: ${shareUrl(v.ref, base)}`].join("\n");

/** X's compose box, filled: the verdict, the counts and the link; within X's 280 characters. Nothing is posted. */
export function postUrl(v, base = SITE) {
  const room = POST_LIMIT - LINK_LENGTH - 1;
  const text = clip(`${prLabel(v.ref)}: ${v.line} ${countsLine(v)} ${BADGE_MESSAGE}.`.replace(/\s+/g, " "), room);
  return `${POST}?text=${encodeURIComponent(text)}&url=${encodeURIComponent(shareUrl(v.ref, base))}`;
}

// ---- the badge ----------------------------------------------------------------------------------------------------------
const width = (text) => Math.round(text.length * 6.4) + 12;
/** brand/checked.svg, byte for byte (the same drawing as web/badge.js's badges). */
export function checkedBadgeSvg() {
  const label = BADGE_LABEL, msg = BADGE_MESSAGE, m = BADGE_MARK.width + 7, a = width(label) + m, b = width(msg);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${a + b}" height="20" viewBox="0 0 ${a + b} 20" role="img" `
    + `aria-label="${label}: ${msg}"><title>Agent pull requests here can be checked by Knos: does the description's "tests pass" meet the checks at its head commit?</title>`
    + `<rect width="${a}" height="20" fill="#24292f"/><rect x="${a}" width="${b}" height="20" fill="#2b3bb5"/>`
    + `<g fill="#fff" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">`
    + `<path fill-rule="evenodd" transform="${BADGE_MARK.transform}" d="${BADGE_MARK.d}"/>`
    + `<text x="${(a + m) / 2}" y="14" textLength="${a - m - 12}">${label}</text>`
    + `<text x="${a + b / 2}" y="14" textLength="${b - 12}">${msg}</text></g></svg>\n`;
}
export const badgeSnippet = (repo, base = SITE) =>
  `[![${BADGE_LABEL} ${BADGE_MESSAGE}](${base}/${BADGE_FILE})](${shareUrl({ owner: repo.owner, repo: repo.repo }, base)})`;

/** "yes" when the repository merged a pull request in the last 30 days, "no", or "limit" (GitHub's 60 reads an hour
 *  are spent). The pull request itself answers first; otherwise one read of its 30 latest closed pull requests. */
export async function repoActive(v, now = Date.now(), get = fetch) {
  const recent = (t) => { const at = Date.parse(t || ""); return Number.isFinite(at) && now - at <= ACTIVE_DAYS * 86_400_000; };
  if (recent(v.merged_at)) return "yes";
  const r = await get(`${API}/repos/${v.ref.owner}/${v.ref.repo}/pulls?state=closed&sort=updated&direction=desc&per_page=30`, { headers: { Accept: "application/vnd.github+json" } });
  if ((r.status === 403 || r.status === 429) && r.headers.get("x-ratelimit-remaining") === "0") return "limit";
  if (!r.ok) return "no";
  const list = await r.json();
  return Array.isArray(list) && list.some((p) => recent(p.merged_at)) ? "yes" : "no";
}

// ---- the card -----------------------------------------------------------------------------------------------------------
function lines(g, text, max, most) {
  const out = [];
  let now = "";
  for (const w of text.split(/\s+/).filter(Boolean)) {
    const next = now ? `${now} ${w}` : w;
    if (g.measureText(next).width <= max || !now) { now = next; continue; }
    out.push(now); now = w;
    if (out.length === most) break;
  }
  if (out.length < most && now) out.push(now);
  else if (now && out.length === most) {
    let last = out[most - 1];
    while (last && g.measureText(`${last}…`).width > max) last = last.slice(0, -1);
    out[most - 1] = `${last.trimEnd()}…`;
  }
  return out;
}

/** Draw the verdict on `canvas` (1200 x 630, CARD of web/brand/card.js). Returns the canvas. */
export function drawCard(canvas, v) {
  const { width: W, height: H, margin: M, colour: C, font: F, row: R } = CARD;
  canvas.width = W; canvas.height = H;
  const g = canvas.getContext("2d"), inner = W - 2 * M;
  const sky = g.createLinearGradient(0, 0, W, H);
  sky.addColorStop(0, C.paper2); sky.addColorStop(1, C.paper);
  g.fillStyle = sky; g.fillRect(0, 0, W, H);
  g.strokeStyle = C.line; g.lineWidth = 2; g.strokeRect(24, 24, W - 48, H - 48);
  // the mark and the name
  g.save(); g.translate(M - 6, R.top - CARD.mark + 4); g.scale(CARD.mark / 1800, CARD.mark / 1800);
  g.fillStyle = C.ink; g.fill(new Path2D(BADGE_MARK.d), "evenodd"); g.restore();
  g.textBaseline = "alphabetic"; g.fillStyle = C.ink; g.font = `700 34px ${F.head}`; g.fillText("Knos", M + CARD.mark, R.top);
  g.font = `500 26px ${F.code}`; g.fillStyle = C.ink2; g.textAlign = "right";
  g.fillText(clip(prLabel(v.ref), 44), W - M, R.top); g.textAlign = "left";
  // the verdict, then the claim
  g.font = `700 50px ${F.head}`; g.fillStyle = C[tone(v)] || C.ink;
  const said = lines(g, v.line || "", inner, 2), below = R.verdict + (said.length - 1) * 56 + 64;
  said.forEach((l, i) => g.fillText(l, M, R.verdict + i * 56));
  g.font = `400 28px ${F.text}`; g.fillStyle = C.ink2;
  lines(g, claimLine(v, 220), inner, said.length > 1 ? 2 : 3).forEach((l, i) => g.fillText(l, M, below + i * 36));
  // the counts: one box per class of failed check
  const c = counts(v), cell = inner / CLASSES.length;
  CLASSES.forEach((name, i) => {
    const x = M + i * cell, n = c[name];
    g.fillStyle = C.paper2; g.strokeStyle = C.line; g.lineWidth = 2;
    g.beginPath(); g.roundRect?.(x, R.counts - 72, cell - 16, 96, 14); g.fill(); g.stroke();
    g.fillStyle = n ? C.bad : C.ink; g.font = `600 40px ${F.code}`; g.fillText(String(n), x + 20, R.counts - 16);
    g.fillStyle = C.ink2; g.font = `400 22px ${F.text}`; g.fillText(`${CLASS_WORDS[name]} failed`, x + 20, R.counts + 12);
  });
  // the signature
  g.fillStyle = C.accent; g.font = `600 26px ${F.text}`; g.fillText(CARD.sign, M, R.foot);
  g.fillStyle = C.ink2; g.font = `400 22px ${F.code}`; g.textAlign = "right"; g.fillText(CARD.host, W - M, R.foot); g.textAlign = "left";
  return canvas;
}

const fontsReady = async () => {
  if (!globalThis.document?.fonts?.load) return;
  const { font: F } = CARD;
  await Promise.all([`700 52px ${F.head}`, `400 28px ${F.text}`, `600 40px ${F.code}`].map((f) => document.fonts.load(f).catch(() => null)));
};
/** The card as a PNG Blob. */
export async function cardBlob(v) {
  await fontsReady();
  const canvas = drawCard(document.createElement("canvas"), v);
  return new Promise((done) => canvas.toBlob(done, "image/png"));
}
export const cardName = (pr) => `knos-check-${pr.owner}-${pr.repo}-${pr.number}.png`;

// ---- the panel ------------------------------------------------------------------------------------------------------------
async function copy(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* a page without the permission: select instead */ }
  const back = document.activeElement;     // the control pressed: the hidden box takes the focus to select, then gives it back
  const t = Object.assign(document.createElement("textarea"), { value: text });
  t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0";
  document.body.append(t); t.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  t.remove();
  back?.focus?.({ preventScroll: true });
  return ok;
}
const say = async (text, kind = "ok") => { try { (await import("./motion.js")).toast(text, kind); } catch { /* no motion: the status line says it */ } };

/** Fill `el` with the share controls for ctx.verdict (web/check.js readPr's answer). ctx: { verdict, esc?, now?, get?, base? }.
 *  The address bar is set to the verdict's link, so the page's own address is the link to share. */
export function renderShare(el, ctx = {}) {
  const v = ctx.verdict, esc = ctx.esc || escHtml, base = ctx.base || SITE, pr = v?.ref;
  if (!el || !pr || !named(pr.owner, pr.repo) || !(Number(pr.number) > 0)) { if (el) el.innerHTML = ""; return; }
  try { if (globalThis.location && location.hash !== shareHash(pr)) history.replaceState(null, "", shareHash(pr)); } catch { /* a page with no history */ }
  const repo = `${pr.owner}/${pr.repo}`;
  el.innerHTML = `<div class="k-share" data-share style="display:flex;flex-wrap:wrap;gap:8px;align-items:center">
  <button type="button" class="k-btn quiet" data-act="copy">Copy the result</button>
  <a class="k-btn quiet" data-act="post" href="${esc(postUrl(v, base))}" target="_blank" rel="noopener">Post on X</a>
  <button type="button" class="k-btn quiet" data-act="card">Download the card</button>
</div>
<p class="fine" data-share-said role="status" aria-live="polite"></p>
<details class="k-more" data-act="badge"><summary>Badge for ${esc(repo)}</summary><div data-badge></div></details>`;
  const said = el.querySelector("[data-share-said]"), tell = (text, kind) => { said.textContent = text; say(text, kind); };
  el.querySelector('[data-act="copy"]').addEventListener("click", async () => {
    tell((await copy(resultText(v, base))) ? "Copied the result and its link." : "Select the text: this browser refused to copy.", "ok");
  });
  const cardBtn = el.querySelector('[data-act="card"]');
  let drawing = false;           // one card at a time; never `disabled`, which drops a keyboard's focus to <body>
  cardBtn.addEventListener("click", async () => {
    if (drawing) return;
    drawing = true; cardBtn.setAttribute("aria-busy", "true"); cardBtn.setAttribute("aria-disabled", "true");
    try {
      const blob = await cardBlob(v), url = URL.createObjectURL(blob);
      const a = Object.assign(document.createElement("a"), { href: url, download: cardName(pr) });
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
      tell("Saved the card: 1200 by 630 pixels.");
    } catch { tell("Drew nothing: this browser has no canvas.", "bad"); }
    cardBtn.removeAttribute("aria-busy"); cardBtn.removeAttribute("aria-disabled"); drawing = false;
  });
  const box = el.querySelector("[data-badge]");
  el.querySelector('[data-act="badge"]').addEventListener("toggle", async (e) => {
    if (!e.target.open || box.dataset.state) return;
    box.dataset.state = "pending"; box.innerHTML = `<p class="fine">Reading ${esc(repo)}'s last merges…</p>`;
    let active = "no";
    try { active = await repoActive(v, ctx.now ?? Date.now(), ctx.get || fetch); } catch { active = "no"; }
    box.dataset.state = active;
    if (active === "limit") { box.innerHTML = `<p class="fine">Wait an hour: GitHub's 60 reads from here are spent.</p>`; delete box.dataset.state; return; }
    if (active !== "yes") { box.innerHTML = `<p class="fine">Offered only to repositories that merged in the last ${ACTIVE_DAYS} days.</p>`; return; }
    const snippet = badgeSnippet(pr, base);
    box.innerHTML = `<p><img src="${esc(BADGE_FILE)}" alt="${esc(`${BADGE_LABEL} ${BADGE_MESSAGE}`)}" height="20"></p>
<pre><code>${esc(snippet)}</code></pre>
<button type="button" class="k-btn quiet" data-act="copy-badge">Copy the badge</button>`;
    box.querySelector('[data-act="copy-badge"]').addEventListener("click", async () => tell((await copy(snippet)) ? "Copied the badge for your README." : "Select the text: this browser refused to copy."));
  });
}
