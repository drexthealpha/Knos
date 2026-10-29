// Knos projects (tranches, attempts, AMC, pools, referrals) and teams (SSO, Squads, ERP, sandbox). Uses app.js's helpers.
"use strict";
(function () {
  const I = window.KNOS_I18N;
  if (I) {
    const nav = { en: ["Projects", "Teams"], fr: ["Projets", "Équipes"], es: ["Proyectos", "Equipos"], pt: ["Projetos", "Equipes"],
      ar: ["المشاريع", "الفرق"], hi: ["परियोजनाएँ", "टीमें"], zh: ["项目", "团队"] };
    for (const [l, [p, tm]] of Object.entries(nav)) if (I[l]) { I[l].nav_projects = p; I[l].nav_teams = tm; }
  }
  try { const r = new URLSearchParams(location.search).get("ref"); if (r && /^[0-9a-f]{12}$/.test(r)) localStorage.setItem("knos.ref", r); } catch (e) { /* private */ }
})();

const V = { templates: null, project: null };
const ref = () => { try { return localStorage.getItem("knos.ref") || undefined; } catch (e) { return undefined; } };
const STATUS = { open: "Open", funded: "Funded", claimed: "In progress", released: "Released", reopened: "Reopened" };

async function walletSign(b64) {
  const w = window.phantom && window.phantom.solana || window.solflare || window.solana;
  if (!w && window.Knos && Knos.wallets && Knos.wallets().length) {     // a Wallet Standard wallet (static/ux_more.js)
    const signed = await Knos.standardSign(Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)));
    const r = await fetch("https://api.devnet.solana.com", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "sendTransaction", params: [btoa(String.fromCharCode(...signed)), { encoding: "base64" }] }) }).then((x) => x.json());
    if (r.error) throw new Error(r.error.message);
    return r.result;
  }
  if (!w) throw new Error("Connect a Solana wallet (Phantom, Solflare) set to devnet to sign this.");
  const web3 = await loadWeb3();
  const tx = web3.Transaction.from(Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)));
  const signed = await w.signTransaction(tx);
  return new web3.Connection("https://api.devnet.solana.com", "confirmed").sendRawTransaction(signed.serialize());
}
async function walletAccount() {
  const w = window.phantom && window.phantom.solana || window.solflare || window.solana;
  if (!w) throw new Error("Connect a Solana wallet (Phantom, Solflare) set to devnet.");
  await w.connect(); return w.publicKey.toString();
}
async function settle(confirmPath, idKey, id, sig) {
  for (let i = 0; i < 10; i++) {
    try { return await api(confirmPath, { [idKey]: id, signature: sig }); } catch (e) { await new Promise((r) => setTimeout(r, 2500)); }
  }
  throw new Error("Sent " + sig.slice(0, 10) + "… but devnet has not shown it yet; refresh in a minute.");
}

// ---- projects --------------------------------------------------------------------------------------------------------
async function loadProjects() {
  const h = location.hash.match(/^#projects=([0-9a-f]{16})/);
  // the list and the templates are asked for together: the list is drawn as soon as it comes, the form after it
  const listing = h ? null : api("/api/projects").catch((e) => { err(e); return { projects: [] }; });
  const tpl = V.templates ? null : api("/api/templates").catch(() => null);
  if (h) { if (!V.templates) V.templates = await tpl; renderNewForm(); return loadProject(h[1]); }
  $("projDetail").hidden = true; $("projHome").hidden = false;
  const got = await listing;
  const box = $("projList");
  box.innerHTML = got.projects.length ? got.projects.map((p) => {
    const locked = p.milestones.reduce((a, m) => a + m.locked_units, 0);
    const done = p.milestones.filter((m) => m.status === "released").length;
    return `<li class="card pcard"><a href="#projects=${p.id}"><strong>${esc(p.title)}</strong></a>
      <p class="small muted">${esc(p.template_name)}${p.regulatory.length ? " · regulated (" + esc(p.regulatory.join(", ").toUpperCase()) + ")" : ""}${p.sandbox ? " · one-day sandbox" : ""}</p>
      <p class="small">${done} of ${p.milestones.length} milestones released · ${locked} test units held</p></li>`;
  }).join("") : `<li class="muted">No projects yet. Open the first one above.</li>`;
  renderPool(got.projects);
  if (!V.templates) V.templates = await tpl;
  renderNewForm();
}
function renderNewForm() {
  renderBriefForm();
  const T = V.templates; if (!T || $("tplPick").dataset.done) return;
  $("tplPick").dataset.done = "1";
  $("tplPick").innerHTML = T.templates.map((t, i) => `<label class="opt"><input type="radio" name="tpl" value="${t.key}" ${i === 0 ? "checked" : ""}>
    <span><strong>${esc(t.name)}</strong><br><span class="small muted">${esc(t.for)} · ${t.milestones.length} milestones</span></span></label>`).join("");
  $("regPick").innerHTML = T.regulatory.sets.map((s) => `<label class="opt"><input type="checkbox" name="reg" value="${s.key}">
    <span>${esc(s.name)} <span class="small muted">(${s.milestones.length} milestones)</span></span></label>`).join("") +
    `<p class="small muted">${esc(T.regulatory.attribution)} <a href="${esc(T.regulatory.source)}" rel="noopener">Source</a>. ${esc(T.regulatory.licence)}</p>`;
}
async function openProject(sandbox) {
  if (!session) { $("signin").hidden = false; throw new Error("Sign in first: a project has an owner."); }
  const tpl = (document.querySelector("input[name=tpl]:checked") || {}).value;
  const regs = [...document.querySelectorAll("input[name=reg]:checked")].map((x) => x.value);
  const p = sandbox ? await api("/api/sandbox", { template: tpl, title: $("pTitle").value.trim() || "One-day sandbox project", team: $("pTeam").value.trim() })
    : await api("/api/project", { template: tpl, title: $("pTitle").value.trim(), regulatory: regs, team: $("pTeam").value.trim() });
  location.hash = "#projects=" + p.id;
}
// the brief's "Grounding (Qloo)" line: the Qloo facts of the demand check this project came from (who, where, price
// tier, comparables), the same facts every agent working on a milestone is handed
function groundingLine(p) {
  const g = p.grounding;
  if (!g) return "";
  const a = g.audience || {}, who = [a.age && String(a.age).replace(/_/g, " "), a.gender, ...(a.segments || [])].filter(Boolean).join(", ");
  const bits = [who && "who: " + who, (g.launch_cities || []).length && "where: " + g.launch_cities.join(", "), g.price_tier && "price tier: " + g.price_tier,
    (g.comparables || []).length && "comparables: " + g.comparables.join(", "),
    // what the person asked Qloo (the demand options), apart from what Qloo answered for the product overall
    Object.keys(g.asked || {}).length && "asked: " + Object.entries(g.asked).map(([k, v]) => `${k.replace(/_/g, " ")} ${Array.isArray(v) ? v.join(", ") : String(v).replace(/_/g, " ")}`).join("; ")].filter(Boolean);
  const src = window.KnosDemand && p.report ? KnosDemand.src("", p.report) : "";       // the trace kept for this project's report
  return bits.length ? `<p class="small" id="grounding" data-qloo><b>Grounding (Qloo)</b>: ${esc(bits.join(" · "))}${src}</p>` : "";
}
// the project's credits (Token-2022 with the knos_hook transfer hook): they move only into this project's holding account
function creditsLine(p) {
  const c = p.credits;
  return c && c.mint ? `<p class="small" id="credits">Project credits: <a class="mono" href="https://explorer.solana.com/address/${esc(c.mint)}?cluster=devnet" rel="noopener">${esc(c.mint.slice(0, 8))}…</a>, held only in the project's own account (a transfer hook refuses any other account).</p>` : "";
}
// who is working on this project, each a separate role you can see: the researcher (what an agent on a milestone is
// handed: the locked intent), the referee (the latest attempt's verdict), the funder (what is held and the rule)
function agents(p) {
  const m = p.milestones.find((x) => x.status !== "released") || p.milestones[0];
  if (!m) return "";
  const a = (m.attempts || []).slice(-1)[0];
  return `<ul class="list small" id="agents-strip" aria-label="Who is working on this">
    <li><strong>Researcher</strong>: <a href="/api/project/prompt?project=${esc(p.id)}&milestone=${esc(m.key)}" rel="noopener">what an agent on "${esc(m.name)}" is handed</a></li>
    <li><strong>Referee</strong>: ${a ? `attempt ${esc(a.id)}, ${esc(a.status)}` : "waiting for an attempt"}</li>
    <li><strong>Funder</strong>: ${m.locked_units} test units held; paid only on a result and an independent check</li></ul>`;
}
const KEPT = {};          // "project:milestone index" -> the milestone's last answer, kept across loadProject's redraw
// every decision on the project in plain words, newest first: each brief version (Ready or not, and why), and each
// milestone's funding, claim, verdict, release, refund and reopen, as the server recorded it (the same lines go to the
// project's decision log in the Knos Record)
function decisions(p) {
  const rows = [...(p.versions || []).map((v) => ({ at: v.at, what: `brief version ${v.n}: ${v.ready ? "Ready to fund" : "not ready"}${v.why ? " (" + v.why + ")" : ""}` })),
    ...p.milestones.flatMap((m) => (m.history || []).map((h) => ({ at: h.at, what: `${m.name}: ${h.what}` })))]
    .sort((a, b) => String(b.at).localeCompare(String(a.at))).slice(0, 40);
  return rows.length ? `<details class="small" id="decisions"><summary>What was decided, and why (${rows.length})</summary><ol class="list">${
    rows.map((r) => `<li><span class="muted">${esc(String(r.at || "").replace("T", " ").slice(0, 16))}</span> ${esc(r.what)}</li>`).join("")}</ol></details>` : "";
}
function dur(s) { return s >= 86400 ? Math.round(s / 86400) + " days" : s >= 3600 ? Math.round(s / 3600) + " h" : Math.round(s / 60) + " min"; }
async function loadProject(id) {
  $("projHome").hidden = true; $("projDetail").hidden = false;
  const p = V.project = await api("/api/project?id=" + id);
  $("projHead").innerHTML = `<p class="small"><a href="#projects">← All projects</a></p><h2>${esc(p.title)}</h2>
    <p class="small muted">${esc(p.template_name)} · opened by ${esc(p.owner_label || "a signed-in user")}${p.team ? " for " + esc(p.team) : ""} · ${esc(p.money)}</p>
    <p class="small">Each milestone's money is held on its own. It pays on a result plus an independent check. A missed deadline refunds and reopens it.</p>
    <div class="row"><button type="button" class="quiet" id="refBtn">Get my referral link</button>
      <a class="button ghost small" href="/api/company/export?project=${p.id}&format=journal">Ledger CSV</a></div><p id="refOut" class="small"></p>
    ${readyLine(p)}${groundingLine(p)}${creditsLine(p)}${changesBlock(p)}${agents(p)}${decisions(p)}
    <details class="small"><summary>A .sol name for this project</summary><label for="snsIn">Name</label><input id="snsIn" maxlength="60" placeholder="myproject.sol">
      <button type="button" class="quiet" id="snsGo">Look it up</button><p id="snsOut" aria-live="polite"></p></details>`;
  wireChanges(p);
  $("snsGo").onclick = () => busy($("snsGo"), "Reading devnet", async () => {      // Name Service: who owns the name on this cluster
    const r = await api("/api/sns?name=" + encodeURIComponent($("snsIn").value.trim()));
    $("snsOut").innerHTML = r.registered ? `${esc(r.name)} is owned by <a href="${X(r.owner, "address")}" rel="noopener">${short(r.owner)}</a>.` : `${esc(r.name)} is not registered on devnet.`;
  });
  $("refBtn").onclick = () => busy($("refBtn"), "Making link", async () => {
    if (!session) { $("signin").hidden = false; throw new Error("Sign in first."); }
    const r = await api("/api/referral", { passkey: true, target: "p=" + p.id });
    $("refOut").innerHTML = `Share <span class="mono">${esc(location.origin + r.link)}</span>: ${esc(r.rule)} (${r.share_bps / 100}%).`;
  });
  $("msList").innerHTML = p.milestones.map((m, i) => msCard(p, m, i)).join("");
  watchOrders(p);
  p.milestones.forEach((m, i) => wire(p, m, i));
  // a step's last answer (the lock, its finality) stays on the card when the project is drawn again after it
  p.milestones.forEach((m, i) => { const k = p.id + ":" + i; if (KEPT[k] && $("o" + i)) $("o" + i).innerHTML = KEPT[k]; });
}
// The code referee's four proofs for one order (knos_wanted.referee.trust): each one checks without Knos.
function trustLine(t) {
  if (!t) return "";
  const a = t.attestation || {};
  const parts = [
    t.run ? `<a href="${esc(t.run)}" rel="noopener">referee run</a>` : `<span class="muted">referee run: waiting for GitHub Actions</span>`,
    t.oidc_verify ? `<a href="${X(t.oidc_verify[0])}" rel="noopener">knos_oidc verification</a>` : `<span class="muted">knos_oidc verification: not yet</span>`,
    a.ok ? `<a href="${esc(a.url || a.rekor || "#")}" rel="noopener">Sigstore attestation</a>${a.rekor && a.url ? ` (<a href="${esc(a.rekor)}" rel="noopener">Rekor</a>)` : ""}` : `<span class="muted">attestation: ${esc(a.why || "not yet")}</span>`,
    t.release ? `<a href="${X(t.release)}" rel="noopener">FROST release</a>` : `<span class="muted">FROST release: ${esc(t.state || "waiting")} (2 of 3 hosts)</span>`,
  ];
  return `<br><span class="small">Code referee: ${parts.join(" · ")}</span>`;
}
// a verified attempt on chain beyond its attestations (knos_wanted.chainx): the maker's badge, the compressed log, the
// release memo, the rent the release returned
function onchainLine(c) {
  if (!c) return "";
  const parts = [];
  if (c.badge && c.badge.mint) parts.push(`<a href="${X(c.badge.mint, "address")}" rel="noopener">badge (Token-2022, cannot be sold)</a>`);
  if (c.log && c.log.signature) parts.push(`<a href="${X(c.log.signature)}" rel="noopener">compressed log leaf ${c.log.index}</a>`);
  if (c.memo && c.memo.signature) parts.push(`<a href="${X(c.memo.signature)}" rel="noopener">release memo</a>`);
  if (c.rent && typeof c.rent.returned_sol === "number") parts.push(`rent returned ${c.rent.returned_sol.toFixed(6)} SOL`);
  return parts.length ? `<br><span class="small">On chain: ${parts.join(" · ")}</span>` : "";
}
// each locked holding account's balance, pushed by devnet as it changes (accountSubscribe): no polling, closed when the page changes
let orderSocket = null;
function watchOrders(p) {
  if (orderSocket) {        // each holding account's stream unsubscribed by the id devnet gave it (accountUnsubscribe), then closed
    const old = orderSocket; orderSocket = null;
    try { Object.keys(old.subs || {}).forEach((id, i) => old.send(JSON.stringify({ jsonrpc: "2.0", id: 900 + i, method: "accountUnsubscribe", params: [Number(id)] }))); } catch (e) { /* closed */ }
    setTimeout(() => { try { old.close(); } catch (e) { /* closed */ } }, 300);
  }
  const orders = p.milestones.flatMap((m) => m.orders.filter((o) => o.status === "locked").map((o) => o.order));
  if (!orders.length || !window.WebSocket) return;
  const ws = orderSocket = new WebSocket("wss://api.devnet.solana.com");
  const ids = {};
  ws.onopen = () => orders.forEach((o, i) => { ids[100 + i] = o; ws.send(JSON.stringify({ jsonrpc: "2.0", id: 100 + i, method: "accountSubscribe", params: [o, { commitment: "confirmed", encoding: "base64" }] })); });
  const subs = ws.subs = {};
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && ids[m.id]) subs[m.result] = ids[m.id];
    if (m.method === "accountNotification") {
      const o = subs[m.params.subscription], v = m.params.result.value;
      const el = document.querySelector(`[data-order="${o}"]`);
      if (el) el.textContent = v ? `live: ${(v.lamports / 1e9).toFixed(6)} SOL in the account` : "live: closed (released or refunded)";
    }
  };
}
function msCard(p, m, i) {
  const live = m.attempts.filter((a) => ["working", "result posted", "checked"].includes(a.status));
  const reg = m.kind === "regulatory" ? `<p class="small"><span class="tag">Regulatory · ${esc(m.standard)}</span> <a href="${esc(m.template)}" rel="noopener">OpenRegulatory template</a></p>` : "";
  const cap = (m.route && m.route.capacity || []).map((c) => `<li>${esc(c.name)}${c.quote && c.quote.price != null ? ` · quote ${c.quote.price} ${esc(c.quote.currency)}, ${c.quote.turnaround_days} days <span class="small muted">(${c.quote.fixture ? "fixture quote, labelled" : "live"})</span>` : ""}${c.manual ? ` · <a href="${esc(c.manual)}" rel="noopener">order on their site</a>` : ""}</li>`).join("");
  const orders = m.orders.map((o) => `<li class="small"><a href="${o.explorer}" rel="noopener">${short(o.order)}</a> <span class="muted" data-order="${esc(o.order)}"></span>${o.receipt && o.receipt.pledge && o.receipt.pledge.signature ? ` · <a href="${X(o.receipt.pledge.signature)}" rel="noopener">pledge receipt</a>` : ""}${o.finality && o.finality.seconds ? ` · release finalized in ${o.finality.seconds} s (${esc(o.finality.via)})` : ""}${o.receipt && o.receipt.refund && o.receipt.refund.burned ? ` · <a href="${X(o.receipt.refund.burned)}" rel="noopener">receipt burned on refund</a>` : ""} ${o.private ? (o.receipt && o.receipt.private && o.receipt.private.range_signature ? `amount private (<a href="${X(o.receipt.private.range_signature)}" rel="noopener">range proof</a>)` : "amount private") : o.units + " units"} · ${esc(o.kind)}${o.grant ? " (" + esc(o.grant.agency) + " " + esc(o.grant.id) + ")" : ""} · <strong>${esc(o.status)}</strong>${o.signatures && o.signatures.refund ? ` · <a href="${X(o.signatures.refund)}" rel="noopener">refund</a>` : ""}${o.signatures && (o.signatures.referee_2_pass || o.signatures.referee_group_pass) ? ` · <a href="${X(o.signatures.referee_2_pass || o.signatures.referee_group_pass)}" rel="noopener">release</a>` : ""}${trustLine(o.trust)}</li>`).join("");
  const atts = m.attempts.map((a) => `<li class="small">${esc(a.maker)} · <strong>${esc(a.status)}</strong>${a.result ? ` · <a href="${esc(a.result.url)}" rel="noopener nofollow">result</a>` : ""}${a.check ? ` · <a href="${esc(a.check.url)}" rel="noopener nofollow">check</a> by ${esc(a.check.by)}` : ""}${a.result ? ` · <a href="/api/attest?project=${p.id}&milestone=${m.key}&attempt=${a.id}" rel="noopener">in-toto attestation</a>` : ""} <span class="mono muted">${esc(a.id)}</span>${a.verdict && a.status === "verdict posted" ? ` · <span id="verdict-${esc(a.id)}">verdict: pass, releases ${new Date(a.verdict.ends_s * 1000).toLocaleTimeString()} unless disputed</span> <button type="button" class="quiet" data-dispute="${esc(a.id)}">Dispute</button>` : ""}${a.status === "disputed" ? " · money stays locked" : ""}${(a.attestations || []).map((t) => ` · <a href="/api/track?wallet=${esc(t.wallet)}" rel="noopener" class="track">${esc(t.role)} track record</a>`).join("")}${onchainLine(a.onchain)}</li>`).join("");
  return `<li class="card ms" id="ms${i}"><div class="row spread"><h3>${esc(m.name)}</h3><span class="chip st-${esc(m.status)}">${esc(STATUS[m.status] || m.status)}</span></div>
    ${reg}<p class="small muted">Deadline ${dur(m.deadline_s)} after funding · ${m.locked_units} test units held · ${m.amc_units} committed (AMC)${m.excluded_makers ? ` · ${m.excluded_makers} maker(s) missed it` : ""}</p>
    ${orders ? `<ul class="list">${orders}</ul>` : ""}${atts ? `<p class="small"><strong>Attempts</strong> (up to 3 in parallel)</p><ul class="list">${atts}</ul>` : ""}
    ${cap ? `<details><summary class="small">Where this work can be bought</summary><ul class="list small">${cap}</ul><p class="small muted">${esc(m.route.rule)}</p></details>` : ""}
    ${m.game ? `<p class="small">Code-scored: attempts also run as a <a href="#contribute">knos.game round</a>.</p>` : ""}
    ${m.status === "released" ? "" : `<details><summary>Fund or commit</summary>
      <label for="u${i}">Test units</label><input id="u${i}" type="number" min="5" max="1000" value="10" inputmode="numeric">
      <label for="k${i}">As</label><select id="k${i}" class="field"><option value="funder">a funder (held now)</option><option value="grant">a grant (held now, labelled)</option><option value="amc">a buyer commitment (pays only when it verifies)</option></select>
      <label class="small"><input type="checkbox" id="pv${i}"> Keep the amount private (encrypted, proven on devnet)</label>
      <div id="g${i}" hidden><label for="ga${i}">Grant agency</label><input id="ga${i}" maxlength="120"><label for="gi${i}">Grant id</label><input id="gi${i}" maxlength="120"></div>
      <button type="button" id="f${i}" ${p.ready && p.ready.ready && p.status !== "cancelled" ? "" : "disabled"}>Approve with my passkey</button><p class="small muted">${p.ready && p.ready.ready ? "Test units. Refunds go back to your passkey wallet." : "Locked until the brief is Ready to fund."}</p>${p.ready && p.ready.ready && p.status !== "cancelled"
        ? `<p class="small">Or from any wallet: <a id="sp${i}" href="${esc(payLink(p.id, m.key, 10))}">Solana Pay</a></p>` : ""}</details>
    <details><summary>Make it</summary>
      <button type="button" class="ghost" id="c${i}">Attempt this milestone</button>
      <label for="e${i}">Evidence page (public https, contains the claim id${m.orders[0] ? ": " + esc(m.orders[0].claim_id) : ""})</label><input id="e${i}" inputmode="url" maxlength="2000" placeholder="https://">
      <label for="a${i}">Attempt id</label><input id="a${i}" maxlength="12" value="${esc((live[0] || {}).id || "")}">
      <div class="row"><button type="button" class="ghost" id="r${i}">Post my result</button><button type="button" class="ghost" id="x${i}">Post an independent check</button></div></details>`}
    <p id="o${i}" class="small" aria-live="polite"></p></li>`;
}
// Solana Pay transaction request (blink.PAY_PATH): the wallet asks this server for the milestone's funding transaction
const payLink = (pid, key, units) => "solana:" + encodeURIComponent(`${location.origin}/api/pay/fund?` + new URLSearchParams({ project: pid, milestone: key, units }));
function wire(p, m, i) {
  const out = (h) => { $("o" + i).innerHTML = h; KEPT[p.id + ":" + i] = h; };
  for (const b of document.querySelectorAll(`#ms${i} button[data-dispute]`)) b.onclick = () => busy(b, "Disputing", async () => {
    const url = $("e" + i).value.trim(); if (!/^https:\/\//.test(url)) throw new Error("Put your evidence page (https) in the evidence field first.");
    const r = await api("/api/project/dispute", { project: p.id, milestone: m.key, attempt: b.dataset.dispute, url });
    out(`Disputed: the money ${esc(r.money)}.`); setTimeout(() => loadProject(p.id), 800);
  });
  const k = $("k" + i); if (!k) return;
  k.onchange = () => { $("g" + i).hidden = k.value !== "grant"; };
  if ($("sp" + i)) $("u" + i).oninput = () => { $("sp" + i).href = payLink(p.id, m.key, parseInt($("u" + i).value, 10) || 5); };
  $("f" + i).onclick = () => busy($("f" + i), "Approve on your passkey", async () => {
    if (!session) { $("signin").hidden = false; throw new Error("Sign in with your passkey first."); }
    const units = parseInt($("u" + i).value, 10);
    if (k.value === "amc") {
      const a = await KnosPasskey.approve(await api("/api/project/amc", { passkey: true, project: p.id, milestone: m.key, units }), api);
      const sig = (a.signatures || {}).approve;
      out(`Committed ${esc(a.units)} test units: paid to the maker only when it verifies.${sig ? ` <a href="${X(sig)}" rel="noopener">Allowance on devnet</a>.` : ""}`);
    } else {
      const grant = k.value === "grant" ? { agency: $("ga" + i).value, id: $("gi" + i).value } : undefined;
      const priv = $("pv" + i) && $("pv" + i).checked;
      const f = await KnosPasskey.approve(await api("/api/project/fund", { passkey: true, project: p.id, milestone: m.key, units, kind: k.value, grant, ref: ref(), private: priv }), api);
      const sig = (f.signatures || {}).lock;
      out(`Held until the proof passes.${sig ? ` <a href="${X(sig)}" rel="noopener">On devnet</a>.` : ""} <span id="fin${i}">Waiting for finality…</span> <span id="pz${i}"></span>`);
      if (priv && window.Knos && Knos.privatePledge) {
        $("pz" + i).textContent = "Encrypting the amount and proving it…";
        Knos.privatePledge(f.order, units, api).then((r) => { const e = $("pz" + i), z = (r.receipt || {}).private || {};
          if (e) e.innerHTML = z.range_signature ? `Amount private: <a href="${X(z.pubkey_signature)}" rel="noopener">key proof</a> and <a href="${X(z.range_signature)}" rel="noopener">range proof</a> verified by devnet's ZK ElGamal program.` : "Proofs not posted."; })
          .catch((e2) => { const e = $("pz" + i); if (e) e.textContent = "Private proofs failed: " + e2.message; });
      }
      if (window.Knos) { Knos.haptic("lock"); if (Knos.celebrate) Knos.celebrate("Locked"); }
      if (sig && window.Knos) Knos.finality(sig).then((r) => {
        const said = r.seconds ? `Finalized in ${r.seconds.toFixed(1)} s (${r.via}).` : "Not finalized yet.", k = p.id + ":" + i;
        KEPT[k] = (KEPT[k] || "").replace(/<span id="fin\d+">[^<]*<\/span>/, `<span id="fin${i}">${esc(said)}</span>`);   // kept for the redraw
        const e = $("fin" + i); if (e) e.textContent = said;
      });
    }
    setTimeout(() => loadProject(p.id), 1500);
  });
  $("c" + i).onclick = () => busy($("c" + i), "Claiming", async () => {
    if (!session) { $("signin").hidden = false; throw new Error("Sign in first."); }
    const a = await api("/api/project/claim", { passkey: true, project: p.id, milestone: m.key });
    $("a" + i).value = a.id; out(`Attempt ${esc(a.id)} is yours; you are paid to your passkey wallet.`);
  });
  for (const [b, role] of [["r", "result"], ["x", "check"]]) $(b + i).onclick = () => busy($(b + i), "Fetching the page", async () => {
    if (!session) { $("signin").hidden = false; throw new Error("Sign in first."); }
    const r = await api("/api/project/post", { project: p.id, milestone: m.key, attempt: $("a" + i).value.trim(), url: $("e" + i).value.trim(), role });
    if (r.released && window.Knos) { Knos.haptic("release"); if (Knos.celebrate) Knos.celebrate("Released"); }
    out(r.verdict ? `Verdict posted: pays automatically after the ${dur(r.verdict.window_s)} dispute window.` : r.released ? (r.milestone === "signing" ? "Verified: 2 of 3 referee hosts are checking the review and signing the release." : `Released: ${r.released.map((x) => esc(x.status)).join(", ")}.`) : `Posted. Next: ${esc(r.next)}.`);
    setTimeout(() => loadProject(p.id), 1500);
  });
}
function renderPool(projects) {
  const open = []; projects.forEach((p) => p.milestones.forEach((m) => { if (m.status !== "released") open.push({ p, m }); }));
  $("poolBox").hidden = open.length < 2;
  $("poolPick").innerHTML = open.slice(0, 24).map((x, i) => `<label class="opt"><input type="checkbox" name="pool" value="${i}" data-p="${x.p.id}" data-m="${x.m.key}">
    <span>${esc(x.m.name)} <span class="small muted">· ${esc(x.p.title)}</span></span></label>`).join("");
}
async function pool() {
  if (!session) { $("signin").hidden = false; throw new Error("Sign in with your passkey first."); }
  const picks = [...document.querySelectorAll("input[name=pool]:checked")].map((x) => ({ project: x.dataset.p, milestone: x.dataset.m }));
  if (picks.length < 2 || picks.length > 8) throw new Error("Pick 2 to 8 milestones.");
  const total = parseInt($("poolUnits").value, 10), each = Math.floor(total / picks.length);
  if (each < 5) throw new Error(`At least 5 test units per milestone (${5 * picks.length}).`);
  const r = await api("/api/project/pool", { passkey: true });
  const sigs = [];
  for (const x of picks) {          // one holding account per milestone, one passkey approval each
    const f = await KnosPasskey.approve(await api("/api/project/fund", { passkey: true, ...x, units: each, kind: "pool", pool: r.pool, ref: ref() }), api);
    sigs.push((f.signatures || {}).lock || f.order);
  }
  $("poolOut").innerHTML = `Pooled ${each * sigs.length} test units over ${sigs.length} milestones: ` + sigs.map((s) => `<a href="${X(s)}" rel="noopener">${short(s)}</a>`).join(" ");
}

// ---- Ready to fund: the free check before any money locks (knos.ready on the server, POST /api/ready) ---------------
function briefFromForm() {
  const kind = $("bKind").value, d = parseInt($("bDays").value, 10);
  const verifier = kind === "machine" ? { kind, check: $("bCheck").value } :
    { kind, what: $("bWhat").value, how: $("bHow").value, who: $("bWho").value, where: $("bWhere").value };
  const win = parseInt($("bWindow").value, 10);
  return { milestones: [{ key: "m1", name: $("bName").value, target: $("bTarget").value, verifier,
    ...(d > 0 ? { deadline_days: d } : {}) }], kill_fee_bps: Math.round((parseFloat($("bKill").value) || 0) * 100),
    challenge_s: win > 0 ? win : 72 * 3600 };
}
function fillBrief(t) {
  $("bName").value = t.name || ""; $("bTarget").value = t.target || ""; $("bDays").value = t.deadline_days || "";
  $("bKind").value = t.verifier.kind; $("bKind").onchange();
  if (t.verifier.kind === "machine") $("bCheck").value = t.verifier.check || "";
  else for (const f of ["what", "how", "who", "where"]) $("b" + f[0].toUpperCase() + f.slice(1)).value = t.verifier[f] || "";
}
let briefTimer = 0, briefSeq = 0;
async function checkBrief() {
  const seq = ++briefSeq;
  const r = await api("/api/ready", { brief: briefFromForm() });
  if (seq !== briefSeq) return r;          // a newer check is on its way: only the answer to the form as it is now is drawn
  const box = $("bReady"), ok = r.ready;
  $("bLock").disabled = !ok;
  box.className = "ready " + (ok ? "ok" : "bad");
  const m = r.milestones[0] || {};
  const t = r.idt || {};
  // the route an agent run gets (knos.idt.route): fast path at low effort, or the rewrite flow; and its token budget
  const route = t.effort ? `<p class="small muted" id="bRoute">${t.path === "fast" ? "Fast path" : t.path === "rewrite" ? "Needs a rewrite" : "Full reasoning"} · agent effort ${esc(t.effort)} · budget ${Number(t.token_budget).toLocaleString()} output tokens</p>` : "";
  const readings = !ok && (t.interpretations || []).length ? `<p class="small">Which did you mean?</p><div class="row" id="bReadings">${t.interpretations.map((x, i) =>
    `<button type="button" class="quiet" data-reading="${i}">${esc(x.reading)}: ${esc(x.target)}</button>`).join("")}</div>` : "";
  const ask = !ok && t.question ? `<p class="small" id="bQuestion"><strong>One question:</strong> ${esc(t.question)}</p>` : "";
  box.innerHTML = (ok ? `<strong id="bLabel">Ready</strong> · criteria <span class="mono">${esc(r.criteria_hash.slice(0, 12))}</span>`
    : `<strong id="bLabel">Not ready</strong><ul class="list small" id="bMissing">${r.missing.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` +
      (m.rewrite ? `<button type="button" class="quiet" id="bRewrite">Use the rewrite</button>` : "")) + readings + ask + route +
    (t.benchmark ? `<p class="small muted" id="bSaving">Over ${Number(t.benchmark.tasks)} measured briefs Ready used ${esc(t.benchmark.overall_ratio)}x fewer output tokens; Ready passed ${Math.round(100 * t.benchmark.ready_pass_rate)}%, vague ${Math.round(100 * t.benchmark.vague_pass_rate)}%. <a href="${esc(t.benchmark.raw)}" rel="noopener">Raw runs</a>.</p>` : "");
  if (!ok && m.rewrite) $("bRewrite").onclick = () => { fillBrief(m.rewrite); checkBrief().catch(err); };
  const money = ($("bTarget").value || "").match(/(\d[\d,]*(?:\.\d+)?)\s*(EUR|GBP|SOL|BTC|ETH)\b/i);
  if (money) api(`/api/price?pair=${money[2].toUpperCase()}/USD`).then((px) => {      // Pyth's price account on devnet
    const v = parseFloat(money[1].replace(/,/g, "")) * px.price;
    box.insertAdjacentHTML("beforeend", `<p class="small muted" id="bPrice">${esc(money[1])} ${esc(money[2].toUpperCase())} ≈ ${v.toLocaleString("en-US", { maximumFractionDigits: 2 })} USD (<a href="${esc(px.explorer)}" rel="noopener">Pyth on devnet</a>)</p>`);
  }).catch(() => {});
  for (const b of box.querySelectorAll("button[data-reading]")) b.onclick = () => {
    const x = t.interpretations[+b.dataset.reading];
    $("bTarget").value = x.target;
    (window.Knos ? Knos.queue("/api/ready/resolve", { word: x.word, reading: x.reading, target: x.target })
      : api("/api/ready/resolve", { word: x.word, reading: x.reading, target: x.target })).catch(() => {});      // offered first next time
    checkBrief().catch(err);
  };
  return r;
}
function renderBriefForm() {
  if ($("briefBox") || !$("tplPick")) return;
  const sec = document.createElement("div");
  sec.id = "briefBox"; sec.className = "card";
  sec.innerHTML = `<h3>Your brief</h3><p class="small muted">Money locks only when each milestone has a number to hit, who checks it, and a deadline. The check is free.</p>
    <label for="bName">Milestone</label><input id="bName" maxlength="160" placeholder="Checkout p95 latency">
    <label for="bTarget">Target (a number and unit, or a test name)</label><input id="bTarget" maxlength="300" placeholder="p95 under 300 ms on test_checkout">
    <label for="bKind">Checked by</label><select id="bKind" class="field"><option value="machine">a GitHub check or test</option><option value="human">a person (lab, document)</option></select>
    <div id="bMachine"><label for="bCheck">Check or test name</label><input id="bCheck" maxlength="100" placeholder="ci / test_checkout"></div>
    <div id="bHuman" hidden><label for="bWhat">What is measured</label><input id="bWhat" maxlength="200"><label for="bHow">How</label><input id="bHow" maxlength="200">
      <label for="bWho">Who measures it</label><input id="bWho" maxlength="200"><label for="bWhere">Where it is published</label><input id="bWhere" maxlength="200"></div>
    <div class="row"><span><label for="bDays">Deadline (days)</label><input id="bDays" type="number" min="1" max="90" inputmode="numeric" value="14"></span>
      <span><label for="bKill">Kill fee (%)</label><input id="bKill" type="number" min="0" max="50" step="1" inputmode="numeric" value="10"></span>
      <span><label for="bWindow">Dispute window (s)</label><input id="bWindow" type="number" min="60" inputmode="numeric" value="259200"></span></div>
    <p id="bReady" class="ready" role="status" aria-live="polite"></p>
    <p class="small muted" id="bKillNote"></p>
    <button type="button" id="bLock" disabled>Open and fund</button>`;
  $("tplPick").closest("section, .card, div").before(sec);
  $("bKind").onchange = () => { const h = $("bKind").value === "human"; $("bHuman").hidden = !h; $("bMachine").hidden = h; };
  const kn = () => { $("bKillNote").textContent = `If you cancel after funding, the maker keeps ${parseFloat($("bKill").value) || 0}% as the kill fee.`; };
  for (const el of sec.querySelectorAll("input, select")) el.addEventListener("input", () => { kn(); clearTimeout(briefTimer); briefTimer = setTimeout(() => checkBrief().catch(err), 250); });
  kn(); checkBrief().catch(err);
  $("bLock").onclick = () => busy($("bLock"), "Opening", async () => {
    if (!session) { $("signin").hidden = false; throw new Error("Sign in with your passkey first."); }
    const r = await checkBrief(); if (!r.ready) throw new Error("Not ready to fund yet.");
    // a brief written from a demand check carries its report: its Qloo facts become the brief's "Grounding (Qloo)" line
    let report; try { report = sessionStorage.getItem("knos.report") || undefined; } catch (e) { report = undefined; }
    const p = await api("/api/project", { template: "custom", title: $("pTitle").value.trim() || $("bName").value.trim(), brief: briefFromForm(), report });
    try { sessionStorage.removeItem("knos.report"); } catch (e) { /* private window */ }
    location.hash = "#projects=" + p.id;
  });
}
function readyLine(p) {
  const r = p.ready || {};
  const fz = p.frozen ? ` · locked criteria <span class="mono" id="critHash">${esc(p.frozen.criteria_hash.slice(0, 12))}</span>` : "";
  return `<p class="small"><span class="chip ${r.ready ? "st-funded" : "st-open"}" id="readyChip">${r.ready ? "Ready to fund" : "Not ready"}</span>${fz}` +
    ` · kill fee ${(p.kill_fee_bps || 0) / 100}% · dispute window ${dur(p.challenge_s || 259200)}${p.status === "cancelled" ? " · <strong>cancelled</strong>" : ""}</p>` +
    (r.ready ? "" : `<ul class="list small">${(r.missing || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`);
}
function changesBlock(p) {
  const rows = (p.changes || []).map((c) => `<li class="small">Change ${esc(c.id)}: ${esc(c.why || "new criteria")} · <strong id="ch-${esc(c.id)}">${esc(c.status)}</strong>
    ${c.status === "proposed" ? `<button type="button" class="quiet" data-ch="${esc(c.id)}" data-ok="1">Accept</button><button type="button" class="quiet" data-ch="${esc(c.id)}" data-ok="0">Reject</button>` : ""}</li>`).join("");
  const propose = p.frozen && p.status !== "cancelled" ? `<details><summary class="small">Propose a change (the maker accepts or rejects)</summary>
    <label for="chTarget">New target for "${esc(p.milestones[0].name)}"</label><input id="chTarget" maxlength="300" value="${esc(p.milestones[0].target || "")}">
    <button type="button" class="ghost" id="chSend">Send change request</button></details>
    <button type="button" class="quiet" id="pCancel">Cancel the project (kill fee ${(p.kill_fee_bps || 0) / 100}%)</button>` : "";
  return `<div id="changes">${rows ? `<ul class="list">${rows}</ul>` : ""}${propose}<p id="chOut" class="small" aria-live="polite"></p></div>`;
}
function wireChanges(p) {
  const out = (h) => { $("chOut").innerHTML = h; };
  for (const b of document.querySelectorAll("#changes button[data-ch]")) b.onclick = () => busy(b, "Deciding", async () => {
    const r = await api("/api/project/change/decide", { project: p.id, change: b.dataset.ch, accept: b.dataset.ok === "1" });
    out(`Change ${esc(r.status)}.`); setTimeout(() => loadProject(p.id), 800);
  });
  if ($("chSend")) $("chSend").onclick = () => busy($("chSend"), "Sending", async () => {
    const b = { milestones: p.milestones.map((m, i) => ({ key: m.key, name: m.name, target: i === 0 ? $("chTarget").value : m.target,
      verifier: m.verifier, deadline_s: m.deadline_s })), kill_fee_bps: p.kill_fee_bps, challenge_s: p.challenge_s };
    const r = await api("/api/project/change", { project: p.id, brief: b, why: "new target: " + $("chTarget").value.slice(0, 120) });
    out(`Change ${esc(r.id)} sent to the maker.`); setTimeout(() => loadProject(p.id), 800);
  });
  if ($("pCancel")) $("pCancel").onclick = () => busy($("pCancel"), "Cancelling", async () => {
    const r = await api("/api/project/cancel", { project: p.id });
    out(`Cancelled. ${r.orders.map((o) => `${esc(o.status)}${o.kill_fee_units ? `, kill fee ${o.kill_fee_units} units to the maker` : ""}`).join("; ")}`);
    setTimeout(() => loadProject(p.id), 1500);
  });
}

// ---- teams -----------------------------------------------------------------------------------------------------------
async function loadTeams() {
  const c = await api("/api/sso/config").catch(() => ({ enabled: false }));
  $("ssoNote").textContent = c.enabled ? `Through SAML Jackson. Test IdP: ${c.test_idp}.` : "Single sign-on is not switched on on this server.";
  $("ssoBtn").disabled = !c.enabled; if (!$("ssoTenant").value) $("ssoTenant").value = c.test_tenant || "knos-test";
  const tt = c.test_tenants || [];
  $("ssoTenants").innerHTML = tt.map((x) => `<option value="${esc(x.tenant)}">`).join("");
  $("ssoTest").innerHTML = c.enabled ? tt.map((x) => `<li class="small">Test tenant <button type="button" class="quiet" data-tenant="${esc(x.tenant)}">${esc(x.tenant)}</button> · ${esc(x.idp)}</li>`).join("") : "";
  for (const b of $("ssoTest").querySelectorAll("button[data-tenant]")) b.onclick = () => { $("ssoTenant").value = b.dataset.tenant; $("ssoBtn").click(); };
  const got = await api("/api/companies").catch(() => ({ companies: [] }));
  $("coList").innerHTML = got.companies.map((x) => `<li class="small"><strong>${esc(x.name)}</strong> · ${x.threshold} of ${x.members.length} · ${esc(x.status)} · <a href="${X(x.multisig, "address")}" rel="noopener">multisig</a> · vault <span class="mono">${short(x.vault)}</span></li>`).join("") || `<li class="muted small">No companies yet.</li>`;
  const pr = await api("/api/projects").catch(() => ({ projects: [] }));
  $("erpProject").innerHTML = pr.projects.map((p) => `<option value="${p.id}">${esc(p.title)}</option>`).join("");
  $("tplCount").textContent = V.templates ? V.templates.templates.length : 5;
  const pf = await api("/api/proofs").catch(() => ({ proofs: [] }));
  const li = (x) => `<li class="small"><details><summary><strong>${esc(x.title)}</strong> · ${esc(x.result)} · ${esc(x.where)} · ${esc((x.ran_at || "").slice(0, 10))}</summary>
    <p>${esc(x.summary)}</p>${(x.run_yourself || []).length ? `<p class="muted">Run it yourself:</p><pre class="mono">${esc(x.run_yourself.join("\n"))}</pre>` : ""}</details></li>`;
  $("proofList").innerHTML = (pf.proofs || []).map(li).join("") || `<li class="muted small">No recorded proofs in this build.</li>`;
  $("erpProofs").innerHTML = (pf.proofs || []).filter((x) => x.key.startsWith("erp_")).map(li).join("") || `<li class="muted small">None recorded.</li>`;
}
async function companyCreate() {
  if (session) {                  // the passkey makes the company's own wallet, which creates the multisig: no wallet app
    const others = $("coMembers").value.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
    const c = await KnosPasskey.approve(await api("/api/company/multisig", { passkey: true, name: $("coName").value, members: others,
      threshold: parseInt($("coThreshold").value, 10) }), api);
    $("coOut").innerHTML = `Created by your passkey: <a href="${c.explorer}" rel="noopener">multisig ${short(c.multisig)}</a>${c.signatures && c.signatures.create ? ` · <a href="${X(c.signatures.create)}" rel="noopener">transaction</a>` : ""}, vault <span class="mono">${esc(c.vault)}</span>.`;
    return loadTeams();
  }
  const creator = await walletAccount();
  const members = [creator, ...$("coMembers").value.split(/[\s,]+/).map((s) => s.trim()).filter((s) => s && s !== creator)];
  const r = await api("/api/company/multisig", { name: $("coName").value, members, threshold: parseInt($("coThreshold").value, 10), creator });
  const sig = await walletSign(r.transaction); const c = await settle("/api/company/confirm", "company", r.company, sig);
  $("coOut").innerHTML = `Created: <a href="${c.explorer}" rel="noopener">multisig ${short(c.multisig)}</a>, vault <span class="mono">${esc(c.vault)}</span>. Knos holds no key in it.`;
  loadTeams();
}

window.KNOS_VIEW = function (view) {
  if (view === "projects") loadProjects();
  if (view === "teams") loadTeams();
};
document.addEventListener("DOMContentLoaded", () => {
  $("pNew").onclick = () => busy($("pNew"), "Opening", () => openProject(false));
  $("pSandbox").onclick = () => busy($("pSandbox"), "Opening", () => openProject(true));
  $("sbBtn").onclick = () => { location.hash = "#projects"; setTimeout(() => $("pSandbox").click(), 50); };
  $("poolBtn").onclick = () => busy($("poolBtn"), "Approve on your passkey", pool);
  $("ssoBtn").onclick = () => { location.href = "/auth/sso?tenant=" + encodeURIComponent($("ssoTenant").value.trim()); };
  $("coBtn").onclick = () => busy($("coBtn"), "Waiting for your wallet", companyCreate);
  const exp = (fmt) => () => { const p = $("erpProject").value; if (p) location.href = `/api/company/export?project=${p}&format=${fmt}`; };
  for (const f of ["journal", "xero", "quickbooks", "netsuite"]) $("erp_" + f).onclick = exp(f);
});
