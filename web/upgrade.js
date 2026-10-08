// Is an upgrade of either program waiting? The upgrade multisig (a Squads v4 multisig) decides every change to knos_pay and
// knos_oidc, and an approved one waits out a time lock before it can run, so what is pending is on chain for anyone to
// read. These are the minimal reads of it: the multisig's newest proposals, and what each one would run. Same layouts and
// the same answers as pending_proposals in src/knos/mainnet_check.py (and the proposal reads of scripts/governance.mjs);
// tests/web/site.mjs holds this file to the answers recorded in tests/web/recorded/squads_upgrades.json.
//
// Squads v4 accounts are borsh behind an 8-byte Anchor discriminator, every Vec has a u32 count:
//   Proposal           multisig 32 | transaction index u64 | status: a u8 tag (0 Draft, 1 Active, 2 Rejected, 3 Approved,
//                      4 Executing, 5 Executed, 6 Cancelled), then for every tag but 4 the i64 time it entered it | bump u8 |
//                      approved: Vec<Pubkey> | rejected | cancelled
//   VaultTransaction   multisig 32 | creator 32 | index u64 | bump, vault index, vault bump | ephemeral signer bumps: Vec<u8> |
//                      message: three signer counts, account keys: Vec<Pubkey>, instructions: Vec<(program index u8,
//                      account indexes: Vec<u8>, data: Vec<u8>)>, address table lookups
//   addresses          proposal ["multisig", multisig, "transaction", index u64 LE, "proposal"]; transaction without the last seed
// The upgradeable loader's Upgrade is data 03 00 00 00 with accounts [programdata, program, buffer, ...].
// An approved proposal can run once the time lock has passed since it was approved; an active one is still short of votes.

export const LOOK_BACK = 10;      // how many of the newest proposals are read, as in src/knos/mainnet_check.py
export const STATUSES = ["Draft", "Active", "Rejected", "Approved", "Executing", "Executed", "Cancelled"];
const PROPOSAL = [26, 94, 189, 187, 116, 136, 53, 33];          // sha256("account:Proposal")[0..8], tests check it
const VAULT_TX = [168, 250, 162, 100, 81, 14, 162, 207];        // sha256("account:VaultTransaction")[0..8]
const CONFIG_TX = [94, 8, 4, 35, 113, 139, 139, 112];           // sha256("account:ConfigTransaction")[0..8]
export const DISCRIMINATORS = { PROPOSAL, VAULT_TX, CONFIG_TX };

const enc = new TextEncoder();
const is = (raw, tag) => raw && raw.length >= 8 && tag.every((b, i) => raw[i] === b);
const dv = (raw) => new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
const u64 = (n) => { const out = new Uint8Array(8); new DataView(out.buffer).setBigUint64(0, BigInt(n), true); return out; };

export const proposalAddress = async (knos, multisig, index) => (await knos.findProgramAddress([enc.encode("multisig"), knos.unb58(multisig), enc.encode("transaction"), u64(index), enc.encode("proposal")], knos.SQUADS))[0];
export const transactionAddress = async (knos, multisig, index) => (await knos.findProgramAddress([enc.encode("multisig"), knos.unb58(multisig), enc.encode("transaction"), u64(index)], knos.SQUADS))[0];

// A Proposal account: { index, status, at, approved }; null for anything else. `at` is when it entered that status (0 for Executing).
export function readProposal(raw) {
  if (!is(raw, PROPOSAL) || raw.length < 8 + 32 + 8 + 1) return null;
  const tag = raw[48], v = dv(raw);
  if (tag >= STATUSES.length) return null;
  let at = 49, when = 0;
  if (tag !== 4) { if (raw.length < at + 8) return null; when = Number(v.getBigInt64(at, true)); at += 8; }
  at += 1;
  if (raw.length < at + 4) return null;
  const count = v.getUint32(at, true);
  if (count > 65_535 || raw.length < at + 4 + 32 * count) return null;
  return { index: Number(v.getBigUint64(40, true)), status: STATUSES[tag], at: when, approved: count };
}

// What a transaction account would run: { kind: "upgrade", program, buffer } when it carries the upgradeable loader's Upgrade,
// { kind: "config" } for a change to the multisig itself, { kind: "other" } for the rest, and for an account that is cut short.
export function readTransaction(knos, raw) {
  if (is(raw, CONFIG_TX)) return { kind: "config" };
  if (!is(raw, VAULT_TX)) return { kind: "other" };
  try {
    const v = dv(raw), at8 = (n) => { if (n > raw.length) throw new RangeError("short"); return n; };
    let at = at8(8 + 32 + 32 + 8 + 3);
    at = at8(at + 4 + v.getUint32(at, true));          // the ephemeral signer bumps
    at = at8(at + 3);                                    // the three signer counts
    const nkeys = v.getUint32(at, true);
    at8(at + 4 + 32 * nkeys);
    const keys = Array.from({ length: nkeys }, (_, k) => knos.b58(raw.subarray(at + 4 + 32 * k, at + 36 + 32 * k)));
    at += 4 + 32 * nkeys;
    const count = v.getUint32(at, true);
    at += 4;
    for (let i = 0; i < count; i++) {
      const program = raw[at], n = v.getUint32(at + 1, true);
      at8(at + 5 + n);
      const accounts = [...raw.subarray(at + 5, at + 5 + n)];
      at += 5 + n;
      const size = v.getUint32(at, true);
      at8(at + 4 + size);
      const body = raw.subarray(at + 4, at + 4 + size);
      at += 4 + size;
      if (program >= keys.length) throw new RangeError("no such key");
      if (keys[program] === knos.LOADER && body.length >= 4 && body[0] === 3 && body[1] === 0 && body[2] === 0 && body[3] === 0 && accounts.length >= 3) {
        if (accounts[1] >= keys.length || accounts[2] >= keys.length) throw new RangeError("no such key");
        return { kind: "upgrade", program: keys[accounts[1]], buffer: keys[accounts[2]] };
      }
    }
  } catch { /* cut short or not what it should be: not read as an upgrade */ }
  return { kind: "other" };
}

// The unfinished proposals (Draft, Active, Approved) among the newest `lookBack` of the multisig, newest first, each as
// { index, status, approved, threshold, kind, program, buffer, executesAt }. Proposals at or below the stale index are void and not read;
// one that is not on chain was never made. `ms`: knos.readMultisig of the multisig's account. executesAt: approval time + the time lock,
// null until it is approved.
export async function pendingProposals(knos, rpc, multisig, ms, lookBack = LOOK_BACK) {
  const indexes = [];
  for (let i = ms.transactionIndex; i > Math.max(ms.staleTransactionIndex, ms.transactionIndex - lookBack); i--) indexes.push(i);
  if (!indexes.length) return [];
  const got = await knos.accounts(rpc, await Promise.all(indexes.map((i) => proposalAddress(knos, multisig, i))));
  const open = indexes.map((index, k) => ({ index, p: got[k]?.owner === knos.SQUADS ? readProposal(got[k].data) : null })).filter((x) => x.p && ["Draft", "Active", "Approved"].includes(x.p.status));
  if (!open.length) return [];
  const txs = await knos.accounts(rpc, await Promise.all(open.map((x) => transactionAddress(knos, multisig, x.index))));
  return open.map(({ index, p }, k) => {
    const t = readTransaction(knos, txs[k]?.owner === knos.SQUADS ? txs[k].data : null);
    return { index, status: p.status, approved: p.approved, threshold: ms.threshold, kind: t.kind, program: t.program ?? null, buffer: t.buffer ?? null, executesAt: p.status === "Approved" ? p.at + ms.timeLock : null };
  });
}

// The programs the upgrade multisig holds, by address: every one program_ids.json names (scripts/upgrade_feed.py PROGRAMS).
export const PROGRAMS = ["knos_oidc", "knos_pay", "knos_meter", "knos_passkey"];
export const programNames = (ids) => Object.fromEntries(PROGRAMS.filter((n) => typeof ids[n] === "string" && ids[n]).map((n) => [ids[n], n]));

// The upgrades of the Knos programs that are waiting, with the program's name: [{ ...pending, name: "knos_pay" }]. `ids`: program_ids.json.
export async function pendingUpgrades(knos, rpc, ids) {
  const raw = await knos.account(rpc, ids.upgrade_multisig), ms = knos.readMultisig(raw);
  if (!ms) return { upgrades: [], ms: null };
  const names = programNames(ids);
  const all = await pendingProposals(knos, rpc, ids.upgrade_multisig, ms);
  return { ms, upgrades: all.filter((p) => p.kind === "upgrade" && names[p.program]).map((p) => ({ ...p, name: names[p.program] })) };
}

const when = (t) => `${new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ")} UTC`;
// "in 41 h 12 min": how long from `now` (the chain's clock) to `t`
export function inWords(t, now) {
  const left = Math.max(0, t - now);
  return `${Math.floor(left / 3600)} h ${Math.floor((left % 3600) / 60)} min`;
}

// Whole hours from `now` until an approved upgrade can run: the time a funder has to take money out (scripts/upgrade_feed.py hours_to_leave)
export const hoursToLeave = (t, now) => Math.floor(Math.max(0, t - now) / 3600);

// What a pending upgrade is, in two sentences. `lock`: the multisig's time lock in seconds. `now`: the chain's clock, or null when it could
// not be read (then no countdown is given, and nothing is said about the delay being over).
export function upgradeWords(p, lock, now) {
  const what = `An upgrade of ${p.name} is pending: it would replace the program's code with the bytes in the buffer`;
  if (p.status === "Approved") {
    const delay = now === null ? `it can be run from ${when(p.executesAt)}`
      : now >= p.executesAt ? `its delay is over (${when(p.executesAt)}), so a member can run it now` : `it can be run from ${when(p.executesAt)}, in ${inWords(p.executesAt, now)}`;
    const leave = now === null || now >= p.executesAt ? "" : ` ${hoursToLeave(p.executesAt, now)} hours to leave: knos exit --before-upgrade lists what you hold and how to take it out before then.`;
    return { what, state: `The multisig has approved it (${p.approved} of ${p.threshold} members); ${delay}.${leave}` };
  }
  if (p.status === "Active") return { what, state: `${p.approved} of ${p.threshold} approvals so far. It can be run ${Math.round(lock / 3600)} hours after the vote that approves it.` };
  return { what, state: "It is drafted and not yet put to the members' vote." };
}

// The day an approved upgrade of `name` can first be run, as "2026-10-05"; null when none is approved
export function runDay(upgrades, name) {
  const p = upgrades.filter((x) => x.name === name && x.status === "Approved").sort((a, b) => a.executesAt - b.executesAt)[0];
  return p ? new Date(p.executesAt * 1000).toISOString().slice(0, 10) : null;
}

// Being told without looking: scripts/upgrade_feed.py writes every proposal (program, proposed build hash, source commit, earliest
// execution time, status) to upgrades.json and to an Atom feed beside this file, at release time and with every build of the site.
// A feed reader that follows the feed shows a new proposal when the site is next built; the banner above reads the chain itself.
export const FEED = "upgrades.xml";
export const FEED_JSON = "upgrades.json";
// The banner's last line, on every view while a proposal is pending.
export const feedLine = `<p class="fine">Follow every proposal without opening this page: <a id="upgrade-feed" href="${FEED}" type="application/atom+xml">the upgrade feed (Atom)</a>,
  or <a href="${FEED_JSON}">the same as JSON</a>: program, build hash, source commit, earliest time it can run, and whether it is pending, executed, cancelled or replaced.</p>`;
