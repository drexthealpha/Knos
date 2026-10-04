// The first screen beyond the pull-request check (front.js): the recording, three example buttons that fill the first
// form with real inputs (config.js), and the one input front.js does not know, the transaction that paid a task.
// Nothing here is sent anywhere: a transaction is read from Solana devnet, the rest from GitHub, as in app.js.
import { CONFIG } from "./config.js";

const SIG = /^[1-9A-HJ-NP-Za-km-z]{64,90}$/;

// A transaction signature, or the explorer's link to one; null for anything else.
export function parseTx(s) {
  const t = String(s || "").trim();
  const m = /^https:\/\/explorer\.solana\.com\/tx\/([1-9A-HJ-NP-Za-km-z]{64,90})(?:[/?#].*)?$/.exec(t);
  const sig = m ? m[1] : t;
  return SIG.test(sig) ? sig : null;
}

// The `knos:paid` and `knos2:paid` lines the escrow itself printed in a transaction (a line another program prints in
// the same transaction is not one), as { deployment, repo, issue, payee, amount, fee, to, pr }. `programs`: the
// escrow's address -> 1 or 2 for the deployment it belongs to. The same rule as src/knos/records.py events_of.
export function paidLines(tx, programs) {
  const stack = [], out = [];
  for (const line of tx?.meta?.logMessages || []) {
    if (/^Program \w+ invoke \[\d+\]$/.test(line)) { stack.push(line.split(" ")[1]); continue; }
    if (/^Program \w+ (success|failed)/.test(line)) { stack.pop(); continue; }
    const m = /^Program log: (knos2?):paid(?: (.*))?$/.exec(line);
    if (!m || programs[stack.at(-1)] !== (m[1] === "knos" ? 1 : 2)) continue;
    const f = Object.fromEntries((m[2] || "").split(" ").filter((kv) => kv.includes("=")).map((kv) => kv.split(/=(.*)/s).slice(0, 2)));
    out.push({ deployment: programs[stack.at(-1)], repo: f.repo, issue: f.issue, payee: f.author ?? f.payee, amount: Number(f.amount), fee: Number(f.fee), to: f.to, pr: f.pr });
  }
  return out;
}

// The recording: shown only once the browser has the file's metadata, so a release with no recording, a missing asset
// or a file the browser cannot play leaves no empty box on the page.
export function showVideo(doc, video = CONFIG.video) {
  const fig = doc.getElementById("demo"), el = doc.getElementById("demo-video");
  const ok = (s) => typeof s === "string" && /^(https:\/\/[^\s"'<>]+|[\w./-]+)$/.test(s.trim());
  if (!fig || !el || !video || !ok(video.src)) return;
  el.addEventListener("loadedmetadata", () => { fig.hidden = false; }, { once: true });
  el.addEventListener("error", () => { fig.hidden = true; }, { once: true });
  if (ok(video.poster)) el.poster = video.poster.trim();
  el.src = video.src.trim();
}

export function initFirst(ctx) {
  const { $, esc, knos, RPC, EXPLORER, money } = ctx;
  showVideo(document);

  // the three buttons: put a real input in the form and press it for the reader
  const box = $("examples");
  if (box) {
    box.innerHTML = CONFIG.examples.map((e) => `<button type="button" class="ghost small" data-example="${esc(e.id)}">${esc(e.label)}</button>`).join(" ");
    box.addEventListener("click", (ev) => {
      const e = CONFIG.examples.find((x) => x.id === ev.target.closest?.("[data-example]")?.dataset.example);
      if (!e) return;
      $("pr-url").value = e.input;
      $("example-says").textContent = e.says;
      $("pr-form").requestSubmit();
    });
  }

  async function readPaid(sig) {
    const out = $("pr-result");
    out.innerHTML = `<p class="status">Reading Solana devnet…</p>`;
    try {
      await ctx.devnet();
      const first = [...document.querySelectorAll("#first-deployment .mono")][1]?.textContent.trim();
      const programs = { [(await ctx.ids()).knos_pay]: 2, ...(first ? { [first]: 1 } : {}) };
      // version 1: what a relay sends to a 2.1 cluster. Asked for with 0, devnet refuses every payment a relay carried
      const tx = await knos.rpc(RPC, "getTransaction", [sig, { encoding: "json", maxSupportedTransactionVersion: 1, commitment: "confirmed" }]);
      if (!tx) throw new Error("Devnet has no transaction with that signature. It may be older than devnet keeps, or from another network.");
      const where = `<a href="${esc(EXPLORER("tx", sig))}" target="_blank" rel="noopener">${esc(sig.slice(0, 8))}…</a>`;
      if (tx.meta?.err) { out.innerHTML = `<p class="status bad">That transaction failed on devnet, so it paid nothing (${where}).</p>`; return; }
      const paid = paidLines(tx, programs);
      if (!paid.length) { out.innerHTML = `<p id="verdict" class="verdict" data-verdict="not a payment">Not a payment by Knos</p><p class="fine">This transaction (${where}) has no payment line from either escrow program.</p>`; return; }
      const named = async (path, key, fallback) => ctx.gh(path).then((r) => r[key]).catch(() => fallback);
      const rows = await Promise.all(paid.map(async (p) => `<dl class="facts paid-facts">
        <dt>Task</dt><dd>issue #${esc(p.issue)} of ${esc(await named(`/repositories/${p.repo}`, "full_name", `repository ${p.repo}`))}${p.pr ? `, pull request #${esc(p.pr)}` : ""}</dd>
        <dt>Paid to</dt><dd>${esc(await named(`/user/${p.payee}`, "login", `GitHub user ${p.payee}`))} (GitHub id ${esc(p.payee)})</dd>
        <dt>Kept by the escrow</dt><dd>${money(p.fee, 6, 2)} test USDC, the fee</dd>
        <dt>Escrow program</dt><dd>${p.deployment === 1 ? "first" : "second"} deployment</dd></dl>`));
      const total = paid.reduce((n, p) => n + p.amount, 0), time = tx.blockTime ? `${new Date(tx.blockTime * 1000).toISOString().slice(0, 16).replace("T", " ")} UTC` : "no time recorded";
      out.innerHTML = `<p id="verdict" class="verdict ok" data-verdict="paid">Paid: ${money(total, 6, 2)} test USDC</p>${rows.join("")}
        <p class="fine">Block time ${esc(time)}, transaction ${where}. This is read from the escrow's own log line in that transaction on Solana devnet.
          It is test USDC: devnet money is worth nothing.</p>`;
    } catch (e) { out.innerHTML = `<p class="status bad">${esc(e.message)}</p>`; }
  }

  // front.js answers pull requests and repositories; a transaction goes here instead (document capture runs first)
  document.addEventListener("submit", (ev) => {
    if (ev.target.id !== "pr-form") return;
    const sig = parseTx($("pr-url").value);
    if (!sig) return;
    ev.stopImmediatePropagation(); ev.preventDefault();
    readPaid(sig);
  }, true);
  document.addEventListener("paste", (ev) => {
    if (ev.target.id !== "pr-url" || !parseTx(ev.clipboardData?.getData("text"))) return;
    ev.stopImmediatePropagation();
    setTimeout(() => $("pr-form").requestSubmit(), 0);
  }, true);
}
