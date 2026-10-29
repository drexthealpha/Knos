// #network "network facts": what Solana devnet says about itself, read in this browser when the section comes near the
// screen (web/app.js later()). Every value is an RPC answer as it came; a method this RPC refuses is said so, never
// guessed. A 429 is retried with backoff (1 s, 2 s, 4 s, 8 s).
// Live, over the cluster's WebSocket (no polling): slotSubscribe + rootSubscribe (the finality clock) and logsSubscribe
// on Knos's two programs (an activity feed). The genesis hash is checked first: an endpoint that is not devnet is refused.
const DEVNET = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG";
// Solana's public devnet RPC, then a second free one that needs no account (Triton's devnet pool): used when the first
// keeps answering 429 or cannot be reached
export const ENDPOINTS = ["https://api.devnet.solana.com", "https://devnet.rpcpool.com"];
export const WSS = ["wss://api.devnet.solana.com", "wss://devnet.rpcpool.com"];
const FEATURE = "Feature111111111111111111111111111111111111";
const MEMO = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr";
const TEST_MINT = "5XJJTDxBF1LqbQ9MAURyYUnHCPcd4JHxjdy9or2gWjsX";   // the lab holding program's test-unit mint (labs_devnet.json)
const RELAYER = "FRXXJkfpwasEpttH5dvDwkySuJzL5D5swjA52U7TMeRD";  // the app's relayer: buyers' AMC allowances are approved to it
const TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// an unanswered fact, short enough for a phone's table cell (the reason, cut to its first words)
const no = (e) => "not answered: " + String(e).replace(/\s+/g, " ").slice(0, 28);
const num = (n) => (typeof n === "number" ? n.toLocaleString("en-US") : String(n));

let id = 0;
/** One JSON-RPC call: 429 -> backoff and retry; any other failure -> {error}. */
export async function rpc(method, params = [], url = ENDPOINTS[0], fetcher = globalThis.fetch) {
  for (let i = 0; i < 4; i++) {
    let r;
    try {
      r = await fetcher(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: ++id, method, params }) });
    } catch (e) { return url === ENDPOINTS[0] ? rpc(method, params, ENDPOINTS[1], fetcher) : { error: `unreachable (${e.message})` }; }
    if (r.status === 429) {                 // a method devnet throttles for everyone answers the same on a retry: said at once
      const said = typeof r.text === "function" ? await r.text().catch(() => "") : "";
      if (/specific RPC call/i.test(said)) return { error: "throttled for this method" };
      await sleep(1000 * 2 ** i); continue;
    }
    const j = await r.json().catch(() => ({ error: { message: `HTTP ${r.status}` } }));
    return j.error ? { error: j.error.message || String(j.error.code) } : { result: j.result };
  }
  return url === ENDPOINTS[0] ? rpc(method, params, ENDPOINTS[1], fetcher) : { error: "rate limited (429) after 4 tries" };
}

const ALPHA = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
export function b58decode(s) {
  let n = 0n;
  for (const c of s) n = n * 58n + BigInt(ALPHA.indexOf(c));
  const out = [];
  while (n > 0n) { out.unshift(Number(n % 256n)); n /= 256n; }
  for (const c of s) { if (c !== "1") break; out.unshift(0); }
  return Uint8Array.from(out);
}
/** A legacy message of one Memo instruction paid by `payer`: what getFeeForMessage prices before anyone signs. */
export function memoMessage(payer, blockhash, text = "knos fee preview") {
  const data = new TextEncoder().encode(text);
  const parts = [Uint8Array.of(1, 0, 1, 2), b58decode(payer), b58decode(MEMO), b58decode(blockhash), Uint8Array.of(1, 1, 1, 0, data.length), data];
  const out = new Uint8Array(parts.reduce((a, p) => a + p.length, 0));
  let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
  return btoa(String.fromCharCode(...out));
}

/** The facts, as rows of [name, value, method]. `payer`: any address (the fee preview's payer). */
export async function facts(payer, call = rpc) {
  const g = await call("getGenesisHash");
  if (g.result && g.result !== DEVNET) return [["cluster", `refused: genesis ${g.result} is not devnet`, "getGenesisHash"]];
  const bh = await call("getLatestBlockhash", [{ commitment: "finalized" }]);
  const hash = bh.result?.value?.blockhash;
  const asks = [
    ["health", "getHealth", [], (r) => r],
    ["node version", "getVersion", [], (r) => r["solana-core"]],
    ["epoch", "getEpochInfo", [{ commitment: "finalized" }], (r) => `${num(r.epoch)}, slot ${num(r.slotIndex)} of ${num(r.slotsInEpoch)}`],
    ["epoch length", "getEpochSchedule", [], (r) => `${num(r.slotsPerEpoch)} slots`],
    ["finalized slot", "getSlot", [{ commitment: "finalized" }], (r) => num(r)],
    ["block height", "getBlockHeight", [{ commitment: "finalized" }], (r) => num(r)],
    ["slots per second (last sample)", "getRecentPerformanceSamples", [1], (r) => r[0] ? (r[0].numSlots / r[0].samplePeriodSecs).toFixed(2) : "none"],
    ["transactions per second", "getRecentPerformanceSamples", [1], (r) => r[0] ? Math.round(r[0].numTransactions / r[0].samplePeriodSecs) : "none"],
    ["cluster nodes", "getClusterNodes", [], (r) => num(r.length)],
    ["vote accounts (current / delinquent)", "getVoteAccounts", [], (r) => `${num(r.current.length)} / ${num(r.delinquent.length)}`],
    ["supply (SOL, circulating)", "getSupply", [{ excludeNonCirculatingAccountsList: true }], (r) => num(Math.round(r.value.circulating / 1e9))],
    ["inflation rate (total)", "getInflationRate", [], (r) => `${(r.total * 100).toFixed(2)}% (epoch ${r.epoch})`],
    ["stake minimum delegation (SOL)", "getStakeMinimumDelegation", [], (r) => (r.value / 1e9).toString()],
    ["priority fee (median of recent, micro-lamports/CU)", "getRecentPrioritizationFees", [], (r) => {
      const f = r.map((x) => x.prioritizationFee).sort((a, b) => a - b); return f.length ? num(f[Math.floor(f.length / 2)]) : "none"; }],
    ["rent for a token account (SOL)", "getMinimumBalanceForRentExemption", [165], (r) => (r / 1e9).toFixed(6)],
    ["largest accounts", "getLargestAccounts", [{ filter: "circulating" }], (r) => `${num(r.value.length)} listed`],
    ["block time of the finalized slot", "getBlockTime", null, (r) => new Date(r * 1000).toISOString().slice(11, 19) + " UTC"],
    ["leader of the next slots", "getSlotLeaders", null, (r) => `${r.length} leaders listed`],
  ];
  const slot = (await call("getSlot", [{ commitment: "finalized" }])).result;
  const rows = [["genesis hash", g.result === DEVNET ? "devnet" : g.error || "?", "getGenesisHash"]];
  // one validator's share (its leader slots this epoch, its vote account's last inflation reward) and the test units'
  // largest holders, asked beside the rest so a throttled method does not hold the table up
  const share = async () => {
    const v0 = (await call("getVoteAccounts", [])).result?.current?.[0];
    if (!v0) return [];
    const [ls, ir] = await Promise.all([call("getLeaderSchedule", [null, { identity: v0.nodePubkey }]), call("getInflationReward", [[v0.votePubkey]])]);
    return [["leader slots this epoch (one validator)", ls.error ? no(ls.error) : num((ls.result?.[v0.nodePubkey] || []).length), "getLeaderSchedule"],
      ["last inflation reward (one vote account, SOL)", ir.error ? no(ir.error) : ir.result?.[0] ? (ir.result[0].amount / 1e9).toFixed(4) : "none", "getInflationReward"]];
  };
  const holders = call("getTokenLargestAccounts", [TEST_MINT]).then((tl) => [["largest holders of the Knos test units",
    tl.error ? no(tl.error) : `${num(tl.result?.value?.length ?? 0)} listed`, "getTokenLargestAccounts"]]);
  // the ledger and the node behind this RPC, and the holding program's own token reads: the test units' supply, and the buyer
  // allowances delegated to the relayer (each AMC commitment is an approve() to it)
  // a block's vote tally is kept only until it is rooted: asked of the newest processed slot
  const tip = (await call("getSlot", [{ commitment: "processed" }])).result ?? slot;
  const ledger = [
    ["transactions processed (finalized)", "getTransactionCount", [{ commitment: "finalized" }], (r) => num(r)],
    ["newest slot's votes (share of stake, deepest lockout)", "getBlockCommitment", [tip], (r) => r.commitment && r.totalStake
      ? `${(100 * r.commitment.reduce((a, x) => a + x, 0) / r.totalStake).toFixed(0)}%` : "none kept by this RPC"],
    ["blocks produced this epoch", "getBlockProduction", [{ commitment: "finalized" }], (r) => num(Object.values(r.value.byIdentity).reduce((a, x) => a + x[1], 0))],
    ["confirmed blocks in the last 10 slots", "getBlocks", [slot - 10, slot], (r) => num(r.length)],
    ["next 5 confirmed blocks from 10 slots back", "getBlocksWithLimit", [slot - 10, 5], (r) => num(r.length)],
    ["first block this RPC still holds", "getFirstAvailableBlock", [], (r) => num(r)],
    ["lowest slot in this RPC's ledger", "minimumLedgerSlot", [], (r) => num(r)],
    ["highest snapshot slot", "getHighestSnapshotSlot", [], (r) => num(r.full)],
    ["this RPC node's identity", "getIdentity", [], (r) => String(r.identity).slice(0, 8) + "…"],
    ["max retransmit slot", "getMaxRetransmitSlot", [], (r) => num(r)],
    ["max shred insert slot", "getMaxShredInsertSlot", [], (r) => num(r)],
    ["leader of this slot", "getSlotLeader", [{ commitment: "finalized" }], (r) => String(r).slice(0, 8) + "…"],
    ["inflation governor (initial / terminal)", "getInflationGovernor", [], (r) => `${(r.initial * 100).toFixed(1)}% / ${(r.terminal * 100).toFixed(1)}%`],
    ["Knos test units in existence", "getTokenSupply", [TEST_MINT], (r) => r.value.uiAmountString],
    ["buyer allowances delegated to the relayer (accounts)", "getTokenAccountsByDelegate", [RELAYER, { programId: TOKEN }, { encoding: "jsonParsed" }], (r) => num(r.value.length)],
  ];
  const [got, more, held, led] = await Promise.all([Promise.all(asks.map(([name, m, p, f]) => call(m, p ?? (m === "getBlockTime" ? [slot] : [slot, 5]))
    .then((r) => [name, r.error ? no(r.error) : f(r.result), m]))), share(), holders,
    Promise.all(ledger.map(([name, m, p, f]) => call(m, p).then((r) => { try { return [name, r.error ? no(r.error) : f(r.result), m]; } catch (e) { return [name, no(e.message), m]; } })))]);
  rows.push(...got, ...more, ...held, ...led);
  if (hash) {
    const v = await call("isBlockhashValid", [hash, { commitment: "processed" }]);
    rows.push(["latest blockhash valid", v.error ? no(v.error) : String(v.result.value), "isBlockhashValid"]);
    const fee = await call("getFeeForMessage", [memoMessage(payer, hash), { commitment: "processed" }]);
    rows.push(["fee for a one-memo transaction (lamports)", fee.error ? no(fee.error) : num(fee.result.value), "getFeeForMessage"]);
  }
  const ft = await call("getProgramAccounts", [FEATURE, { encoding: "base64", dataSlice: { offset: 0, length: 1 } }]);
  rows.push(["active features (feature gate)", ft.error ? no(ft.error) : `${num(ft.result.filter((a) => atob(a.account.data[0]).charCodeAt(0) === 1).length)} of ${num(ft.result.length)}`, "getProgramAccounts"]);
  return rows;
}

export function factsHtml(rows) {
  return `<h3>Network facts, read from devnet now</h3><div class="k-table"><table id="netfacts"><tbody>${rows.map(([n, v, m]) =>
    `<tr><td>${esc(n)}</td><td class="k-num">${esc(v)}</td><td class="mono small">${esc(m)}</td></tr>`).join("")}</tbody></table></div>
    <p class="fine" id="finality-clock" aria-live="polite">Finality clock: connecting…</p><ol class="small" id="activity-feed" aria-label="Knos programs, live"></ol>`;
}

/** Live over the WebSocket: the processed and rooted (finalized) slots, and the logs of `programs`. Returns stop(). */
export function live(el, programs, WS = globalThis.WebSocket) {
  if (!WS) return () => {};
  let slot = 0, root = 0, blocks = 0, updates = 0, votes = 0, ws, at = 0;
  const streams = {}, subs = [];
  const kinds = { 1: "slot", 2: "root", 9: "program", 10: "block", 11: "slotsUpdates", 12: "vote" };
  programs.forEach((_, i) => { kinds[3 + i] = "logs"; });
  const clock = el.querySelector("#finality-clock"), feed = el.querySelector("#activity-feed");
  const open = () => { ws = new WS(WSS[at]); wire(); };
  const wire = () => { ws.onopen = () => {
    ws.send(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "slotSubscribe" }));
    ws.send(JSON.stringify({ jsonrpc: "2.0", id: 2, method: "rootSubscribe" }));
    programs.forEach((p, i) => ws.send(JSON.stringify({ jsonrpc: "2.0", id: 3 + i, method: "logsSubscribe", params: [{ mentions: [p] }, { commitment: "finalized" }] })));
    // a new or changed holding account of the first program, pushed as it happens (the data itself is not needed here)
    // block and slot-update streams: asked for, and the clock says when this RPC does not offer them
    ws.send(JSON.stringify({ jsonrpc: "2.0", id: 10, method: "blockSubscribe", params: ["all", { commitment: "finalized", transactionDetails: "none", rewards: false }] }));
    ws.send(JSON.stringify({ jsonrpc: "2.0", id: 11, method: "slotsUpdatesSubscribe" }));
    if (programs[0]) ws.send(JSON.stringify({ jsonrpc: "2.0", id: 9, method: "programSubscribe", params: [programs[0], { commitment: "confirmed", encoding: "base64", dataSlice: { offset: 0, length: 0 } }] }));
    // votes: only RPCs started with --rpc-pubsub-enable-vote-subscription offer it (the docs' own note); asked, and said when not
    ws.send(JSON.stringify({ jsonrpc: "2.0", id: 12, method: "voteSubscribe" }));
  };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (kinds[m.id] && typeof m.result === "number") subs.push([kinds[m.id], m.result]);   // kept for the unsubscribe on stop
    if (m.method === "slotNotification") slot = m.params.result.slot;
    if (m.method === "rootNotification") root = m.params.result;
    if (m.method === "logsNotification" && feed) {
      const v = m.params.result.value;
      feed.insertAdjacentHTML("afterbegin", `<li><a class="mono" href="https://explorer.solana.com/tx/${esc(v.signature)}?cluster=devnet" rel="noopener">${esc(v.signature.slice(0, 10))}…</a> ${v.err ? "failed" : "finalized"}</li>`);
      while (feed.children.length > 8) feed.lastChild.remove();
    }
    if (m.method === "programNotification" && feed) {
      const k = m.params.result.value.pubkey;
      feed.insertAdjacentHTML("afterbegin", `<li>holding account <a class="mono" href="https://explorer.solana.com/address/${esc(k)}?cluster=devnet" rel="noopener">${esc(k.slice(0, 10))}…</a> changed</li>`);
      while (feed.children.length > 8) feed.lastChild.remove();
    }
    if (m.method === "blockNotification") blocks++;
    if (m.method === "slotsUpdatesNotification") updates++;
    if (m.method === "voteNotification") votes++;
    if ((m.id === 10 || m.id === 11 || m.id === 12) && m.error) streams[m.id] = "not offered by this RPC";
    if (clock && slot && root) clock.textContent = `Finality clock: slot ${num(slot)}, finalized ${num(root)} (${num(slot - root)} behind). `
      + `Blocks: ${streams[10] ? "not offered here" : num(blocks)}. Slot updates: ${streams[11] ? "not offered here" : num(updates)}. `
      + `Votes: ${streams[12] ? "not offered here" : num(votes)}.`;
  };
  ws.onerror = () => {                      // the second RPC's socket when the first does not connect
    if (++at < WSS.length && !slot) open();
    else if (clock) clock.textContent = "Finality clock: the WebSocket did not connect here.";
  }; };
  open();
  // stop: each stream unsubscribed by the id the cluster gave it (<kind>Unsubscribe), then the socket closed
  return () => {
    if (ws && ws.readyState === 1) subs.forEach(([k, id], i) => ws.send(JSON.stringify({ jsonrpc: "2.0", id: 100 + i, method: `${k}Unsubscribe`, params: [id] })));
    setTimeout(() => ws.close(), 400);    // their answers (true) come back before the socket goes
  };
}
