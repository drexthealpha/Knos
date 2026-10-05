// A Balance's limits as data: would one funding pass, which rule decides, and what it costs. Pure functions: nothing
// here reads the page or the network. It is the decision of `knos budget check` (src/knos/controls.py `decide`),
// which repeats the program's own checks in the program's order; tests/web/controls.mjs holds this file and the
// Python to the same answers on the cases of tests/data/controls_cases.json.
//
// The accounts, decoded (decodeBalance, decodeBalx and decodePlan read the bytes the chain holds):
//   balance  { faucet, hasX, ownerId, authority, mint, capPerJob, spenders: [id...], spent }
//   balx     { dayLimit, totalLimit, repos: [id...], wfSha, day, daySpent, totalSpent }   or null: no limits are set
//   plan     { feeBps, ownerId, expires }                                              or null: the standard fee
// Amounts are a mint's smallest units as numbers (USDC: millionths; an order holds at most 100,000 whole units, far
// inside what a number holds exactly). 0 means "no cap", "no limit"; an empty list means "any".
//
// What the program checks when a comment funds an order from a Balance, in this order (its error number):
//   owner 92, spender 92, cap 93, repository 92, workflows 86, day 100, total 100, funds 94, amount 81.
// The cap counts the amount; the limits count what leaves the Balance: the amount and the fee on top.
import { orderFee, priceConstants } from "./price.js";

export const RULES = Object.freeze({ owner: 92, spender: 92, cap: 93, repository: 92, workflows: 86, day: 100, total: 100, funds: 94, amount: 81, ok: 0 });
export const FEE_TABLE = Object.freeze([5, 20, 1_000, 5_000, 50_000]);     // the amounts the price book shows the effective fee for
const DAY = 86_400, UNIT = 1_000_000;

// 400000 -> "0.40", 5000000000 -> "5,000.00": at least two decimals, no zeros past them (no locale is asked)
export function money(units) {
  const whole = Math.floor(units / UNIT), frac = String(units % UNIT).padStart(6, "0").replace(/0+$/, "").padEnd(2, "0");
  return `${String(whole).replace(/\B(?=(\d{3})+$)/g, ",")}.${frac}`;
}
// the fee as a share of the amount in hundredths of a percent, rounded half up: (400000, 5000000) -> "8.00"
export function percent(fee, amount) {
  const h = amount > 0 ? Math.floor((fee * 10_000 + Math.floor(amount / 2)) / amount) : 0;
  return `${Math.floor(h / 100)}.${String(h % 100).padStart(2, "0")}`;
}
// the first tier's rate now: the owner's Plan while it lasts, the standard rate otherwise
export const planBps = (plan, now, c = priceConstants()) => (plan && now < plan.expires ? Math.min(Math.max(plan.feeBps, c.planBpsMin), c.feeBps) : c.feeBps);
// what the side account counts for the UTC day of `now`
export const spentToday = (balx, now) => (balx && balx.day === Math.floor(now / DAY) ? balx.daySpent : 0);

// The effective settle fee at the price book's amounts: [{amount, fee, total, effectivePct}], in millionths.
export function feeTable(bps, c = priceConstants()) {
  return FEE_TABLE.map((a) => { const amount = a * UNIT, fee = orderFee(amount, bps ?? c.feeBps, c); return { amount, fee, total: amount + fee, effectivePct: percent(fee, amount) }; });
}

// Whether a comment by GitHub id `byId` in repository `repoId` may fund an order of `amount` from this Balance, and
// which rule decides. Optional facts, each judged only when given: `plan`, `holds` (what the Balance holds),
// `repoOwnerId` (the id of the repository's owner), `wfSha` (the commit of the workflows the run would use); `now`
// is unix seconds (default: this clock's). Answers { ok, rule, code, sentence, fee, total, effectivePct, bps }.
export function explainFunding({ balance, balx = null, repoId, amount, byId, plan = null, now = Math.floor(Date.now() / 1000), holds = null,
  repoOwnerId = null, wfSha = null }, c = priceConstants()) {
  const bps = planBps(plan, now, c), fee = orderFee(amount, bps, c), total = amount + fee, effectivePct = percent(fee, amount), m = money;
  const cost = `${m(amount)} and a fee of ${m(fee)} (${effectivePct}%) leave the Balance: ${m(total)}`;
  const answer = (rule, sentence) => ({ ok: rule === "ok", rule, code: RULES[rule], sentence, fee, total, effectivePct, bps });
  const spenders = balance.spenders ?? [], x = balance.hasX ? balx : null;
  if (repoOwnerId !== null && repoOwnerId !== balance.ownerId)
    return answer("owner", `Refused: the repository belongs to GitHub id ${repoOwnerId}, and this Balance is for the repositories of GitHub id ${balance.ownerId}. Fund from a repository of that owner.`);
  if (byId === 0 || !(balance.faucet || byId === balance.ownerId || spenders.includes(byId)))
    return answer("spender", `Refused: GitHub id ${byId} is not the owner (${balance.ownerId}) and is not one of this Balance's spenders (${spenders.join(", ") || "none"}). The Balance's wallet can add a spender: knos budget set --spender.`);
  if (balance.capPerJob && amount > balance.capPerJob)
    return answer("cap", `Refused: ${m(amount)} is over the cap of ${m(balance.capPerJob)} for one order. Fund less, or the Balance's wallet raises the cap: knos budget set --cap.`);
  if (x) {
    if (x.repos.length && !x.repos.includes(repoId))
      return answer("repository", `Refused: repository id ${repoId} is not one of the ${x.repos.length} this Balance allows (${x.repos.join(", ")}). The Balance's wallet can allow it: knos budget set --repo.`);
    if (x.wfSha && wfSha !== null && wfSha !== x.wfSha)
      return answer("workflows", `Refused: this Balance accepts only runs of the workflows at commit ${x.wfSha}, and this run is at ${wfSha}. Point the repository's workflow file at that commit, or the Balance's wallet pins another: knos budget set --pin-workflows.`);
    const today = spentToday(x, now);
    if (x.dayLimit && today + total > x.dayLimit)
      return answer("day", `Refused: ${cost}, which with the ${m(today)} already spent today is over the daily limit of ${m(x.dayLimit)}. ${m(Math.max(x.dayLimit - today, 0))} is left until midnight UTC. Fund less, wait, or the Balance's wallet raises it: knos budget set --per-day.`);
    if (x.totalLimit && x.totalSpent + total > x.totalLimit)
      return answer("total", `Refused: ${cost}, which with the ${m(x.totalSpent)} spent so far is over the total limit of ${m(x.totalLimit)}. ${m(Math.max(x.totalLimit - x.totalSpent, 0))} is left. Fund less, or the Balance's wallet raises it: knos budget set --total.`);
  }
  if (holds !== null && holds < total) return answer("funds", `Refused: ${cost}, and the Balance holds ${m(holds)}. Add money to it: knos balance deposit.`);
  if (amount < c.minAmount || amount > c.maxAmount)
    return answer("amount", `Refused: an order holds between ${m(c.minAmount)} and ${m(c.maxAmount)}, and ${m(amount)} is outside that.`);
  return answer("ok", `Fine: ${cost}.`);
}

// ---- the accounts' bytes (a Uint8Array, as getAccountInfo gives them once base64 is undone) ---------------------------
const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
export function base58(bytes) {
  let n = 0n, out = "";
  for (const b of bytes) n = n * 256n + BigInt(b);
  for (; n > 0n; n /= 58n) out = B58[Number(n % 58n)] + out;
  for (const b of bytes) { if (b !== 0) break; out = "1" + out; }
  return out;
}
const view = (d) => new DataView(d.buffer, d.byteOffset, d.byteLength);
const u64 = (d, o) => Number(view(d).getBigUint64(o, true)), i64 = (d, o) => Number(view(d).getBigInt64(o, true));
const ids = (d, o, n) => Array.from({ length: n }, (_, k) => u64(d, o + 8 * k)).filter((v) => v !== 0);

// A Balance (160 bytes), or null when the bytes are not one.
export function decodeBalance(d) {
  if (!d || d.length !== 160 || d[0] !== 1) return null;
  return { faucet: d[2] === 1, hasX: d[3] === 1, ownerId: u64(d, 8), authority: base58(d.subarray(16, 48)), mint: base58(d.subarray(48, 80)),
    capPerJob: u64(d, 80), spenders: ids(d, 96, 4), spent: u64(d, 128) };
}
// A Balance's side account ["balx", balance] (152 bytes), or null.
export function decodeBalx(d) {
  if (!d || d.length !== 152 || d[0] !== 1) return null;
  const sha = d.subarray(88, 128);
  return { dayLimit: u64(d, 8), totalLimit: u64(d, 16), repos: ids(d, 24, 8), wfSha: sha.every((b) => b === 0) ? "" : String.fromCharCode(...sha),
    day: i64(d, 128), daySpent: u64(d, 136), totalSpent: u64(d, 144) };
}
// An owner's Plan ["plan", owner id] (24 bytes), or null.
export function decodePlan(d) {
  if (!d || d.length !== 24 || d[0] !== 1) return null;
  return { feeBps: view(d).getUint16(2, true), ownerId: u64(d, 8), expires: i64(d, 16) };
}
