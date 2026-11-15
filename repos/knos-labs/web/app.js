// Knos web app: hire an agent, review its work, see every agent's record. It reads the escrow on Solana devnet
// directly and builds each transaction here (web/chain.js), so it works with no Knos server at all; your wallet shows
// the transaction and signs it. The API (the relay that carries briefs and sealed work, and Solana Actions) is found
// through a devnet pointer memo, or ?api=. Deliverables are sealed to a key only your wallet can re-derive.
import * as chain from "./chain.js";

const params = new URLSearchParams(location.search);
const CHAIN = params.get("chain") || "solana:devnet";
const $ = (id) => document.getElementById(id);
const state = { wallet: null, account: null, sealKey: null, api: undefined };

// ---- theme -------------------------------------------------------------------------------------------------------
function setTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { t ? localStorage.setItem("knos-theme", t) : localStorage.removeItem("knos-theme"); } catch {}
}
try { const t = localStorage.getItem("knos-theme"); if (t) setTheme(t); } catch {}
$("theme").onclick = () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  setTheme(dark ? "light" : "dark");
};

// ---- routing -----------------------------------------------------------------------------------------------------
const VIEWS = ["check", "hire", "jobs", "agents", "network", "bounty"];
function route() {
  const v = VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "check";
  for (const name of VIEWS) $(`view-${name}`).hidden = name !== v;
  document.querySelectorAll("nav a").forEach((a) => (a.getAttribute("href") === `#${v}`
    ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  ({ jobs: loadJobs, agents: loadAgents, network: loadNetwork })[v]?.();
}
addEventListener("hashchange", route);

// ---- helpers -----------------------------------------------------------------------------------------------------
const b64 = { dec: (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0)),
  enc: (u8) => btoa(String.fromCharCode(...u8)) };
const hex = (u8) => [...u8].map((b) => b.toString(16).padStart(2, "0")).join("");
const unhex = (h) => Uint8Array.from(h.match(/../g).map((x) => parseInt(x, 16)));
const usdc = (n) => Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 6 });
const short = (s) => (s ? `${s.slice(0, 4)}…${s.slice(-4)}` : "—");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const sha256 = async (u8) => new Uint8Array(await crypto.subtle.digest("SHA-256", u8));
function say(el, text, kind = "") { el.textContent = text; el.className = `status ${kind}`; }
const store = {
  get: (k, d) => { try { return JSON.parse(localStorage.getItem(k) || "null") ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

// The API: ?api=, else this origin when it is one (knos jobs serve), else the devnet pointer. Optional everywhere.
async function api() {
  if (state.api !== undefined) return state.api;
  const tries = [params.get("api")];
  if (!/github\.io$/.test(location.hostname)) tries.push(location.origin);
  try { tries.push(await chain.apiUrl()); } catch {}
  for (const u of tries.filter(Boolean)) {
    try {
      const r = await fetch(`${u.replace(/\/$/, "")}/actions.json`, { signal: AbortSignal.timeout(4000) });
      if (r.ok) return (state.api = u.replace(/\/$/, ""));
    } catch {}
  }
  return (state.api = null);
}

// Briefs posted while the relay was unreachable wait here, and go up the next time it answers.
async function flushPendingBriefs() {
  const pending = store.get("knos-pending-briefs", []);
  const base = pending.length ? await api() : null;
  if (!base) return;
  const left = [];
  for (const b of pending) {
    try { const r = await fetch(`${base}/briefs`, { method: "PUT", body: b64.dec(b) }); if (!r.ok) left.push(b); }
    catch { left.push(b); }
  }
  store.set("knos-pending-briefs", left);
}

// ---- wallet (wallet-standard) ------------------------------------------------------------------------------------
let walletsApi;
async function wallets() {
  walletsApi ||= (await import("https://cdn.jsdelivr.net/npm/@wallet-standard/app@1.1.0/+esm")).getWallets();
  return walletsApi.get().filter((w) => w.chains.some((c) => c.startsWith("solana:")) && w.features["standard:connect"]);
}
async function connect() {
  const list = await wallets();
  if (!list.length) throw new Error("No Solana wallet found. Install Phantom, Solflare or Backpack, or pay with a passkey.");
  const w = list.length === 1 ? list[0] : list.find((x) => confirm(`Connect ${x.name}?`)) || list[0];
  const { accounts } = await w.features["standard:connect"].connect();
  state.wallet = w; state.account = accounts[0];
  $("connect").textContent = short(state.account.address);
  return state.account;
}
$("connect").onclick = () => connect().then(route).catch((e) => alert(e.message));

async function signAndSend(txBytes) {
  const f = state.wallet.features["solana:signAndSendTransaction"];
  if (!f) throw new Error("This wallet cannot send transactions.");
  const [out] = await f.signAndSendTransaction({ account: state.account, chain: CHAIN, transaction: txBytes });
  return out.signature;
}

// The delivery key: an X25519 key derived from your wallet's signature of a fixed message. Ed25519 signatures are
// deterministic, so the same wallet re-derives the same key on any device; the key never leaves this page.
let sodiumP;
const sodium = () => (sodiumP ||= import("https://cdn.jsdelivr.net/npm/libsodium-wrappers@0.7.15/+esm")
  .then(async (m) => { const s = m.default || m; await s.ready; return s; }));
async function sealKey() {
  if (state.sealKey) return state.sealKey;
  const f = state.wallet.features["solana:signMessage"];
  if (!f) throw new Error("This wallet cannot sign messages, so it cannot open sealed work.");
  const msg = new TextEncoder().encode(`Knos delivery key v1\n${state.account.address}`);
  const [{ signature }] = await f.signMessage({ account: state.account, message: msg });
  const sk = await sha256(signature);
  const s = await sodium();
  state.sealKey = { sk, pk: s.crypto_scalarmult_base(sk) };
  return state.sealKey;
}

// ---- hire (Solana): the brief goes to the relay, the post transaction is built here ------------------------------
// The key that may pay the worker on proof (`knos verify`); keep in sync with src/knos/jobs/verify.py.
const KNOS_VERIFIER = "9TGQPftNmrt8T6ETUZJ5CeQf27z3pFR8En3FkKrA2PbT";
$("verifier").onchange = () => { $("verifier-key").hidden = $("verifier").value !== "custom"; };
function chosenVerifier() {
  const v = $("verifier").value;
  if (v === "none") return null;
  if (v === "custom") {
    const k = $("verifier-key").value.trim();
    if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(k)) throw new Error("Enter the verifier's public key (base58).");
    return k;
  }
  if (!KNOS_VERIFIER) throw new Error("The Knos reference verifier is not set up yet: choose None or a custom key.");
  return KNOS_VERIFIER;
}
$("hire-form").onsubmit = async (e) => {
  e.preventDefault();
  const st = $("hire-status"); const btn = $("post"); btn.disabled = true;
  try {
    if (!state.account) await connect();
    say(st, "Preparing your delivery key…");
    const { pk } = await sealKey();
    const task = $("task").value.trim(), kind = $("kind").value, units = Math.round(Number($("price").value) * 1e6);
    if (!task || !(units > 0)) throw new Error("Describe the task and set a price.");
    const ghRepo = ($("gh-repo")?.value || "").trim().replace(/^https:\/\/github\.com\//, "").replace(/\/$/, "");
    const gh = ghRepo ? { repo: ghRepo, issue: String(Number($("gh-issue").value) || ""),
      ref: `refs/heads/${($("gh-branch").value || "main").trim()}` } : null;
    if (gh && (!/^[\w.-]+\/[\w.-]+$/.test(gh.repo) || !gh.issue)) throw new Error("Enter the repository (owner/repo) and the issue number.");
    const verifier = gh ? null : chosenVerifier();
    const jobId = crypto.getRandomValues(new Uint8Array(32));
    let checks = null;
    if (gh) { say(st, "Hashing the acceptance tests on GitHub…"); checks = await chain.checksHash(gh.repo, gh.ref.slice(11), gh.issue); }
    const brief = new TextEncoder().encode(JSON.stringify({ title: task.split("\n")[0].slice(0, 80), task, kind,
      checks: null, buyer: state.account.address, price_units: units, created: Math.floor(Date.now() / 1000),
      job_id: hex(jobId), seal_to: hex(pk),
      ...(gh ? { github: { repo: gh.repo, issue: gh.issue, ref: gh.ref, checks_hash: hex(checks) } } : {}) }));
    const briefHash = await sha256(brief);
    const base = await api();
    let held = false;
    if (base) {
      const r = await fetch(`${base}/briefs`, { method: "PUT", body: brief }).catch(() => null);
      held = !r || !r.ok;
    } else held = true;
    if (held) store.set("knos-pending-briefs", [...store.get("knos-pending-briefs", []), b64.enc(brief)]);
    say(st, "Approve in your wallet…");
    const sig = await signAndSend(gh
      ? await chain.postGithubTx(state.account.address, jobId, units, briefHash, gh.repo, gh.ref, checks)
      : await chain.postTx(state.account.address, jobId, units, briefHash, 3600, 86400, verifier));
    const addr = await chain.jobAddress(jobId);
    store.set("knos-job-ids", { ...store.get("knos-job-ids", {}), [addr]: hex(jobId) });
    say(st, `Posted: ${usdc(units / 1e6)} USDC in escrow (${typeof sig === "string" ? sig.slice(0, 10) : "signed"}…).`
      + (gh ? ` A pull request to ${gh.repo} that says "Fixes #${gh.issue}" and "knos-job: ${hex(jobId)}" is paid on proof.` : "")
      + (held ? " The relay is offline right now; this browser hands it the brief when it is back." : ""), "ok");
  } catch (err) { say(st, err.message || String(err), "bad"); } finally { btn.disabled = false; }
};

// ---- hire with a passkey (Tempo): no extension, no seed phrase ---------------------------------------------------
const TEMPO_JOBS = "knos-tempo-jobs";
const tempoJobs = () => store.get(TEMPO_JOBS, []);
async function deviceSealKey() {   // passkey signatures are not deterministic, so the delivery key lives on this device
  const s = await sodium();
  const k = store.get("knos-seal-key", null);
  if (k) return { sk: unhex(k.sk), pk: unhex(k.pk) };
  const kp = s.crypto_box_keypair();
  store.set("knos-seal-key", { sk: hex(kp.privateKey), pk: hex(kp.publicKey) });
  return { sk: kp.privateKey, pk: kp.publicKey };
}
$("post-passkey").onclick = async () => {
  const st = $("hire-status"); const btn = $("post-passkey"); btn.disabled = true;
  try {
    const base = await api();
    if (!base) throw new Error("Tempo jobs need the relay, which is offline right now. Try again later, or use a Solana wallet.");
    const T = await import("./tempo.js");
    say(st, "Use your passkey (Face ID, fingerprint or device PIN)…");
    state.tempo ||= await T.passkeyAccount();
    const addr = state.tempo.address;
    let bal = await T.balance(addr);
    $("passkey-info").hidden = false;
    if (bal < Number($("price").value)) {
      say(st, "Getting free testnet pathUSD from Tempo's faucet…");
      await T.fund(addr);
      for (let i = 0; i < 20 && bal < Number($("price").value); i++) { await new Promise((r) => setTimeout(r, 1000)); bal = await T.balance(addr); }
    }
    $("passkey-info").textContent = `Passkey wallet ${short(addr)} · ${usdc(bal)} pathUSD (Tempo testnet)`;
    say(st, "Approve with your passkey…");
    const { pk } = await deviceSealKey();
    const id = await T.postJob(state.tempo, base, { task: $("task").value.trim(), kind: $("kind").value,
      priceUsd: Number($("price").value), sealTo: hex(pk) });
    store.set(TEMPO_JOBS, [...tempoJobs(), id]);
    say(st, `Posted on Tempo: ${usdc($("price").value)} pathUSD in escrow. See My jobs.`, "ok");
  } catch (err) { say(st, err.message || String(err), "bad"); } finally { btn.disabled = false; }
};
async function loadTempoJobs(box) {
  const ids = tempoJobs();
  if (!ids.length) return;
  const T = await import("./tempo.js");
  const rows = await Promise.all(ids.map((id) => T.job(id).catch(() => null)));
  const html = rows.filter(Boolean).map((j) => `<tr><td class="mono">${j.id.slice(0, 12)}…<div class="fine">Tempo · passkey</div></td>
    <td>${usdc(j.amount)} pathUSD</td><td><span class="pill">${esc(j.state)}</span></td>
    <td>${j.state === "delivered" ? `<button class="small" data-topen="${j.result.slice(2)}">Open</button>
      <button class="small" data-tact="accept" data-id="${j.id}">Accept</button>
      <button class="small ghost" data-tact="reject" data-id="${j.id}">Reject</button>` : ""}</td></tr>`).join("");
  box.insertAdjacentHTML("beforeend", `<h2>On Tempo</h2><div class="table-wrap"><table><tbody>${html}</tbody></table></div>`);
  box.querySelectorAll("[data-topen]").forEach((b) => (b.onclick = () => openDelivery(b.dataset.topen, deviceSealKey).catch((e) => alert(e.message))));
  box.querySelectorAll("[data-tact]").forEach((b) => (b.onclick = async () => {
    try { state.tempo ||= await T.passkeyAccount(); await T.settle(state.tempo, b.dataset.id, b.dataset.tact); loadJobs(); }
    catch (e) { alert(e.message); }
  }));
}

// ---- my jobs: read from the chain; titles and sealed work from the relay when it answers -----------------------
async function briefOf(job) {
  const base = await api();
  if (!base) return null;
  try {
    const r = await fetch(`${base}/briefs/${job.brief}`, { signal: AbortSignal.timeout(4000) });
    if (!r.ok) return null;
    const raw = new Uint8Array(await r.arrayBuffer());
    return hex(await sha256(raw)) === job.brief ? JSON.parse(new TextDecoder().decode(raw)) : null;
  } catch { return null; }
}
async function loadJobs() {
  const box = $("jobs-list");
  if (!state.account) {
    box.innerHTML = ""; $("jobs-hint").hidden = tempoJobs().length > 0;
    return loadTempoJobs(box).catch((e) => box.insertAdjacentHTML("beforeend", `<p class="status bad">${esc(e.message)}</p>`));
  }
  $("jobs-hint").hidden = true;
  box.innerHTML = "<p class='fine'>Reading the escrow on devnet…</p>";
  try {
    const me = state.account.address;
    const mine = (await chain.jobs()).filter((j) => j.buyer === me || j.worker === me).sort((a, b) => b.deadline - a.deadline);
    if (!mine.length) { box.innerHTML = "<p class='lede'>No jobs yet. <a href='#hire'>Hire an agent</a>.</p>"; await loadTempoJobs(box); return; }
    const briefs = await Promise.all(mine.map(briefOf));
    const ids = store.get("knos-job-ids", {});
    box.innerHTML = `<div class="table-wrap"><table><thead><tr><th>Job</th><th>Price</th><th>State</th><th></th></tr></thead><tbody>${
      mine.map((j, i) => { const b = briefs[i], id = (b && b.job_id) || ids[j.address] || "";
        return `<tr><td>${esc((b && b.title) || "Job " + short(j.address))}<div class="fine">${j.buyer === me ? "you hired" : "you worked"} · ${short(j.worker)}</div></td>
        <td>${usdc(j.amount)} USDC</td><td><span class="pill">${esc(j.state)}</span></td>
        <td>${j.buyer === me && j.state === "delivered" ? `<button class="small" data-open="${j.result}">Open</button>
          ${id ? `<button class="small" data-act="accept" data-i="${i}" data-id="${id}">Accept</button>
          <button class="small ghost" data-act="reject" data-i="${i}" data-id="${id}">Reject</button>` : ""}` : ""}</td></tr>`; }).join("")
    }</tbody></table></div>`;
    box.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => openDelivery(b.dataset.open).catch((e) => alert(e.message))));
    box.querySelectorAll("[data-act]").forEach((b) => (b.onclick = () => settle(mine[b.dataset.i], b.dataset.id, b.dataset.act).catch((e) => alert(e.message))));
    await loadTempoJobs(box);
  } catch (err) { box.innerHTML = `<p class="status bad">${esc(err.message)}</p>`; }
}
async function openDelivery(resultHex, keyFn = sealKey) {
  const base = await api();
  if (!base) throw new Error("The relay holding the sealed work is offline right now. Try again later.");
  const r = await fetch(`${base}/deliveries/${resultHex}`);
  if (!r.ok) throw new Error("The relay does not have this delivery.");
  const blob = new Uint8Array(await r.arrayBuffer());
  if (hex(await sha256(blob)) !== resultHex) throw new Error("The relay's copy does not match what the agent committed on chain.");
  const { sk, pk } = await keyFn();
  const s = await sodium();
  let text;
  let sealed = blob, digest = null;
  if (new TextDecoder().decode(blob.slice(0, 18)) === '{"knos-envelope":1') {     // a verified job: the buyer's copy
    const e = JSON.parse(new TextDecoder().decode(blob));
    sealed = Uint8Array.from(atob(e.buyer), (c) => c.charCodeAt(0)); digest = e.digest;
  }
  try {
    const plain = s.crypto_box_seal_open(sealed, pk, sk);
    if (digest && hex(await sha256(plain)) !== digest) throw new Error("not the committed work");
    text = new TextDecoder().decode(plain);
  }
  catch { throw new Error("Sealed to another key: this job was posted outside the web app. Open it with  knos jobs get."); }
  $("delivery-text").textContent = text; $("delivery").hidden = false; $("delivery").scrollIntoView({ behavior: "smooth" });
}
async function settle(job, jobIdHex, verb) {
  const msg = verb === "accept" ? `Pay the agent ${usdc(job.amount - Math.max(job.amount * 0.025, Math.min(job.amount, 0.05)))} USDC (Knos fee: 2.5%, at least 0.05)?` : `Refund ${usdc(job.amount)} USDC to you?`;
  if (!confirm(msg)) return;
  await signAndSend(await chain.settleTx(state.account.address, job, unhex(jobIdHex), verb));
  setTimeout(loadJobs, 1500);
}

// ---- agents and network: counted from the escrow's job accounts ----------------------------------------------
async function loadAgents() {
  const box = $("agents-list");
  try {
    const rows = chain.agents(await chain.jobs());
    box.innerHTML = rows.length ? `<table><thead><tr><th>Agent</th><th>Paid</th><th>Rejected</th><th>Expired</th><th>Acceptance</th><th>Earned</th></tr></thead><tbody>${
      rows.map((a) => `<tr><td class="mono">${esc(a.agent)}</td><td>${a.paid}</td><td>${a.rejected}</td><td>${a.expired}</td>
        <td>${a.acceptance == null ? "—" : Math.round(a.acceptance * 100) + "%"}</td><td>${usdc(a.earned)} USDC</td></tr>`).join("")
    }</tbody></table>` : "<p class='lede'>No agent has finished a job yet.</p>";
  } catch (err) { box.innerHTML = `<p class="status bad">${esc(err.message)}</p>`; }
}
async function loadNetwork() {
  const box = $("network-stats");
  try {
    const n = chain.network(await chain.jobs());
    const s = (v, l) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`;
    box.innerHTML = s(n.all.jobs, "jobs") + s(n.all.paid, "paid out") + s(n.agents, "agents") + s(n.buyers, "buyers")
      + s(usdc(n.all.paidUsdc), "USDC paid to agents") + s(usdc(n.all.escrowUsdc), "USDC in escrow now")
      + `<div class="split"><h2>Knos's own task feed</h2><p class="fine">Jobs posted by Knos's feed key to keep the
        network busy: ${n.feed.jobs} jobs, ${n.feed.paid} paid, ${usdc(n.feed.paidUsdc)} USDC to agents.</p>
        <h2>Everyone else</h2><p class="fine">Jobs from other buyers: ${n.outside.jobs} jobs from ${n.outsideBuyers}
        buyer(s), ${n.outside.paid} paid, ${usdc(n.outside.paidUsdc)} USDC to agents.</p></div>`;
    const base = await api();
    $("api-status").textContent = base ? `Relay and Actions online at ${new URL(base).host}.` : "Relay offline right now: jobs, agents and payouts still read from the chain.";
  } catch (err) { box.innerHTML = `<p class="status bad">${esc(err.message)}</p>`; }
}

flushPendingBriefs();
// ---- bounty: the passkey wallet (web/wallet.js) -------------------------------------------------------------------
{
  let W;
  const wal = async () => (W ||= await import("./wallet.js"));
  const st = $("bw-status");
  const ready = (pk) => { $("bw-addr").textContent = pk; $("bw-usdc").disabled = false; $("bw-fund").disabled = false;
    $("bw-create").textContent = "Wallet ready"; };
  $("bw-create").onclick = async () => {
    try {
      const w = await wal();
      say(st, "Creating your passkey wallet…");
      const pk = (await w.exists()) ? await w.unlock() : await w.create();
      ready(pk);
      const base = await api();
      if (!base) throw new Error("the Knos API is unreachable, so no gas right now");
      say(st, "Getting gas (devnet SOL) from Knos…");
      await w.gas(base);
      say(st, "Wallet ready, with gas.", "ok");
    } catch (e) { say(st, e.message, "err"); }
  };
  $("bw-usdc").onclick = async () => {
    try { const w = await wal(); await w.unlock(); say(st, "Minting test USDC…"); await w.faucet();
      say(st, "Test USDC received.", "ok"); } catch (e) { say(st, e.message, "err"); }
  };
  $("bw-fund").onclick = async () => {
    try {
      const w = await wal(); await w.unlock();
      const units = Math.round(Number($("bw-amount").value || 0) * 1e6);
      say(st, "Funding the issue…");
      const got = await w.fundIssue($("bw-repo").value.trim(), $("bw-issue").value, units);
      st.dataset.job = got.jobId;
      say(st, `Bounty funded: job ${got.jobId.slice(0, 12)}… (${usdc(units / 1e6)} USDC in escrow)`, "ok");
    } catch (e) { say(st, e.message, "err"); }
  };
}

route();
