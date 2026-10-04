// Offline tests of scripts/governance.mjs: no cluster, no key of ours. What it must agree with is written by the Python
// client (scripts/governance_fixture.py -> tests/fixtures/governance_v2.json) and by programs-v2/program_ids.json.
//
//   node --test scripts/governance.test.mjs        (npm ci --prefix scripts first; tests/test_governance.py runs this too)
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";

import * as web3 from "@solana/web3.js";
import * as squads from "@sqds/multisig";

import * as gov from "./governance.mjs";

const { Keypair, PublicKey } = web3;
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const FIXTURE = JSON.parse(fs.readFileSync(path.join(ROOT, "tests", "fixtures", "governance_v2.json"), "utf8"));
const IDS = JSON.parse(fs.readFileSync(path.join(ROOT, "programs-v2", "program_ids.json"), "utf8"));
const pk = (s) => new PublicKey(s);
const GUARDIAN = pk(FIXTURE.guardian);
const { payer: PAYER, buffer: BUFFER, spill: SPILL, key_hash: KEY_HASH } = FIXTURE.inputs;

/** An instruction as the fixture writes it. */
const asFixture = (ix) => ({ program: ix.programId.toBase58(), data: ix.data.toString("hex"),
                             accounts: ix.keys.map((k) => ({ pubkey: k.pubkey.toBase58(), signer: k.isSigner, writable: k.isWritable })) });

// ---- the pinned values --------------------------------------------------------------------------------------------
test("the fixture was written for the ids this repository pins", () => {
  assert.equal(FIXTURE.programs.knos_oidc, IDS.knos_oidc);
  assert.equal(FIXTURE.programs.knos_pay, IDS.knos_pay);
  assert.equal(FIXTURE.programs.squads, IDS.squads_program);
  assert.equal(FIXTURE.guardian, IDS.guardian);
  assert.equal(FIXTURE.multisigs.upgrade.multisig, IDS.upgrade_multisig);
  assert.equal(FIXTURE.multisigs.upgrade.vault, IDS.upgrade_authority);
  assert.equal(FIXTURE.multisigs.guardian.multisig, IDS.guardian_multisig);
  assert.equal(FIXTURE.multisigs.guardian.vault, IDS.guardian);
});

test("the script's table says what each multisig must be", () => {
  assert.deepEqual(Object.keys(gov.WHICH), ["upgrade", "guardian"]);
  assert.equal(gov.WHICH.upgrade.timeLock, 172_800);       // 48 hours
  assert.equal(gov.WHICH.guardian.timeLock, 0);
  for (const name of ["upgrade", "guardian"]) {
    assert.equal(gov.WHICH[name].timeLock, FIXTURE.multisigs[name].time_lock);
    assert.equal(gov.WHICH[name].multisig, FIXTURE.multisigs[name].multisig);
    assert.equal(gov.WHICH[name].vault, FIXTURE.multisigs[name].vault);
  }
  assert.equal(squads.PROGRAM_ID.toBase58(), IDS.squads_program, "the SDK is for the Squads program the repository pins");
});

// ---- the upgrade gate ---------------------------------------------------------------------------------------------
const GATE = JSON.parse(fs.readFileSync(path.join(ROOT, "tests", "fixtures", "upgrade_gate.json"), "utf8"));

test("the upgrade gate's record is derived and read as the Python client and the program itself do", () => {
  assert.equal(gov.UPGRADE_GATE.toBase58(), GATE.gate);
  assert.equal(gov.executableHash(Buffer.from(GATE.elf, "hex")), GATE.executable_hash);
  assert.equal(gov.buildRecord(pk(GATE.program), GATE.executable_hash).toBase58(), GATE.record);
  const r = gov.readBuildRecord(Buffer.from(GATE.record_data, "hex"));
  assert.deepEqual([r.program.toBase58(), r.hash, r.commit, Number(r.runId), r.time], [GATE.program, GATE.executable_hash, GATE.commit, GATE.run_id, GATE.time]);
  assert.equal(gov.readBuildRecord(Buffer.from(GATE.record_data, "hex").subarray(1)), null);
});

test("upgrade propose refuses a buffer whose build the gate has not recorded, unless --ungated", () => {
  const [program, hash] = [pk(GATE.program), GATE.executable_hash];
  const info = { owner: gov.UPGRADE_GATE, data: Buffer.from(GATE.record_data, "hex") };
  assert.match(gov.gated(info, "knos_pay", program, hash, false), new RegExp(`^upgrade gate: GitHub's runner built ${hash} from commit ${GATE.commit} \\(run ${GATE.run_id}; record ${GATE.record}\\)$`));
  // no record; a record of another build, of another program; the same bytes in an account the gate does not own
  const other = "00".repeat(32);
  for (const [got, prog, h] of [[null, program, hash], [info, program, other], [info, pk(IDS.knos_oidc), hash], [{ ...info, owner: gov.LOADER }, program, hash]]) {
    assert.throws(() => gov.gated(got, "knos_pay", prog, h, false),
                  (e) => e instanceof gov.Refused && /has no record that GitHub built/.test(e.message) && /--ungated/.test(e.message) && /Nothing was sent/.test(e.message));
    assert.match(gov.gated(got, "knos_pay", prog, h, true), /^upgrade gate: NO record that GitHub built .* --ungated was passed/);
  }
  // the check is in the proposing path, before anything is proposed, and the flag is one the command line takes
  const src = fs.readFileSync(path.join(HERE, "governance.mjs"), "utf8");
  const body = src.slice(src.indexOf("async function upgrade("), src.indexOf("// ---- approve, cancel, execute"));
  assert.ok(body.indexOf("gated(await conn.getAccountInfo(buildRecord(program, hash)") > 0);
  assert.ok(body.indexOf("gated(") < body.indexOf("await propose("), "the gate is asked before the proposal is made");
  assert.match(src, /ungated: \{ type: "boolean" \}/);
  assert.match(src, /--ungated/);
});

// ---- address derivation -------------------------------------------------------------------------------------------
test("each create key gives the multisig and the vault that programs-v2/program_ids.json pins (and the Python client derives)", () => {
  for (const [name, want] of [["upgrade", { multisig: IDS.upgrade_multisig, vault: IDS.upgrade_authority }],
                              ["guardian", { multisig: IDS.guardian_multisig, vault: IDS.guardian }]]) {
    const got = gov.derive(pk(FIXTURE.multisigs[name].create_key));
    assert.equal(got.multisigPda.toBase58(), want.multisig, `${name} multisig`);
    assert.equal(got.vault.toBase58(), want.vault, `${name} vault`);
    assert.equal(got.multisigPda.toBase58(), FIXTURE.multisigs[name].multisig);
  }
});

test("another create key gives other addresses", () => {
  const got = gov.derive(Keypair.generate().publicKey);
  assert.notEqual(got.multisigPda.toBase58(), IDS.upgrade_multisig);
  assert.notEqual(got.vault.toBase58(), IDS.upgrade_authority);
});

test("the accounts our instructions name are the ones the Python client derives", () => {
  assert.equal(gov.keyAccount(0, KEY_HASH).toBase58(), FIXTURE.addresses["key(github)"]);
  assert.equal(gov.keyAccount(1, KEY_HASH).toBase58(), FIXTURE.addresses["key(gitlab)"]);
  assert.equal(gov.pauseAccount().toBase58(), FIXTURE.addresses.pause);
  assert.equal(gov.programData(pk(IDS.knos_pay)).toBase58(), FIXTURE.addresses["programdata(knos_pay)"]);
});

test("a key hash that is not 64 lowercase hex characters, or an issuer that is neither GitHub nor GitLab, is refused", () => {
  for (const bad of ["", "abc", KEY_HASH.toUpperCase(), KEY_HASH + "00", KEY_HASH.slice(0, 63) + "g"]) {
    assert.throws(() => gov.keyAccount(0, bad), /64 lowercase hex characters/, bad);
  }
  assert.throws(() => gov.keyAccount(2, KEY_HASH), /0 \(GitHub\) or 1 \(GitLab\)/);
});

// ---- the instructions a vault signs: bytes and accounts, against the Python client's ---------------------------------
test("Approve and Revoke are knos_oidc's tags 6 and 7 with the guardian as the only signer and the key writable", () => {
  for (const [issuer, label] of [[0, "github"], [1, "gitlab"]]) {
    const key = gov.keyAccount(issuer, KEY_HASH);
    assert.deepEqual(asFixture(gov.keyIx(6, GUARDIAN, key)), FIXTURE.instructions[`guardian approve ${label}`]);
    assert.deepEqual(asFixture(gov.keyIx(7, GUARDIAN, key)), FIXTURE.instructions[`guardian revoke ${label}`]);
  }
});

test("Pause is knos_pay's tag 9 and the seconds as u32, the guardian and the payer signing", () => {
  for (const seconds of [604_800, 600, 0]) {
    assert.deepEqual(asFixture(gov.pauseIx(GUARDIAN, pk(PAYER), seconds)), FIXTURE.instructions[`guardian pause ${seconds}`], `${seconds} s`);
  }
});

test("a pause longer than seven days, or not a whole number of seconds, is refused before anything is built", () => {
  for (const bad of [604_801, -1, 1.5, NaN, 2 ** 32]) {
    assert.throws(() => gov.pauseIx(GUARDIAN, pk(PAYER), bad), /a pause lasts 0 to 604800 seconds/, String(bad));
  }
});

test("the loader's Upgrade is variant 3 with the program data, program, buffer and spill writable and the authority signing", () => {
  const ix = gov.upgradeIx(pk(IDS.knos_pay), pk(BUFFER), pk(IDS.upgrade_authority), pk(SPILL));
  assert.deepEqual(asFixture(ix), FIXTURE.instructions["upgrade knos_pay"]);
  assert.equal(ix.programId.toBase58(), FIXTURE.programs.loader);
});

// ---- the Squads accounts: the SDK's deserialiser against knos.mainnet_check's reading -----------------------------------
test("the Squads SDK reads the Multisig accounts the program wrote as knos.mainnet_check.read_multisig does", () => {
  for (const [name, want] of Object.entries(FIXTURE.squads_accounts)) {
    const info = { data: Buffer.from(want.data, "hex"), owner: squads.PROGRAM_ID, lamports: 0, executable: false };
    const ms = squads.accounts.Multisig.fromAccountInfo(info)[0];
    assert.equal(ms.createKey.toBase58(), want.create_key, name);
    assert.equal(ms.threshold, want.threshold, name);
    assert.equal(ms.timeLock, want.time_lock, name);
    assert.equal(ms.configAuthority.equals(PublicKey.default), want.config_authority === null, name);
    assert.deepEqual(ms.members.map((m) => m.key.toBase58()), want.members, name);
    assert.equal(ms.members.every((m) => m.permissions.mask === 7), true, `${name}: every member may initiate, vote and execute`);
    assert.equal(gov.derive(ms.createKey).multisigPda.toBase58(), FIXTURE.multisigs[name].multisig, `${name}: the multisig's own address`);
  }
  assert.equal(FIXTURE.squads_accounts.upgrade.time_lock, 172_800);
  assert.equal(FIXTURE.squads_accounts.guardian.time_lock, 0);
});

// ---- the loader's accounts -----------------------------------------------------------------------------------------
test("a ProgramData account is read at the offsets the Python reader uses, with or without an upgrade authority", () => {
  const withKey = FIXTURE.loader_accounts.programdata, none = FIXTURE.loader_accounts["programdata, no upgrade authority"];
  const a = gov.readProgramData(Buffer.from(withKey.data, "hex"));
  assert.equal(a.slot, withKey.slot);
  assert.equal(a.authority.toBase58(), withKey.authority);
  assert.equal(a.bytes.length, withKey.program_bytes);
  assert.equal(gov.executableHash(a.bytes), withKey.executable_hash);
  const b = gov.readProgramData(Buffer.from(none.data, "hex"));
  assert.equal(b.authority, null);
  assert.equal(gov.executableHash(b.bytes), none.executable_hash);
  assert.equal(gov.readProgramData(Buffer.from("0100000000", "hex")), null, "not a ProgramData account");
  assert.equal(gov.readProgramData(Buffer.alloc(10)), null);
});

test("a Buffer account is read at its own offsets, and its program bytes hash as solana-verify hashes them", () => {
  const want = FIXTURE.loader_accounts.buffer;
  const got = gov.readBuffer(Buffer.from(want.data, "hex"));
  assert.equal(got.authority.toBase58(), want.authority);
  assert.equal(got.bytes.length, want.program_bytes);
  assert.equal(gov.executableHash(got.bytes), want.executable_hash);
  assert.equal(gov.readBuffer(Buffer.from(FIXTURE.loader_accounts.programdata.data, "hex")), null, "a ProgramData account is not a buffer");
});

test("the executable hash ignores trailing zeros and nothing else", () => {
  const h = gov.executableHash;
  assert.equal(h(Buffer.from([1, 2, 3])), h(Buffer.from([1, 2, 3, 0, 0, 0])));
  assert.notEqual(h(Buffer.from([1, 2, 3])), h(Buffer.from([0, 1, 2, 3])));
  assert.equal(h(Buffer.alloc(0)), h(Buffer.alloc(9)));
});

// ---- the command line, with no network ---------------------------------------------------------------------------------
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "knos-governance-"));
after(() => fs.rmSync(tmp, { recursive: true, force: true }));
const keyFile = (name) => {
  const file = path.join(tmp, name);
  fs.writeFileSync(file, JSON.stringify([...Keypair.generate().secretKey]));
  return file;
};

/** Runs the script. Any cluster it tries to reach is one nobody listens at, so a test that needs a network fails loudly. */
function run(...args) {
  const env = { ...process.env, KNOS_RPC: "http://127.0.0.1:9", KNOS_KEYS: path.join(tmp, "no-such-folder") };
  delete env.KNOS_FEE_PAYER;
  delete env.KNOS_MEMBERS;
  const r = spawnSync(process.execPath, [path.join(HERE, "governance.mjs"), ...args], { encoding: "utf8", timeout: 60_000, env });
  return { code: r.status, out: r.stdout, err: r.stderr };
}

test("derive: the two public create keys give the pinned addresses, and says so", () => {
  const r = run("derive", "--upgrade-create-key", FIXTURE.multisigs.upgrade.create_key, "--guardian-create-key", FIXTURE.multisigs.guardian.create_key);
  assert.equal(r.code, 0, r.err);
  assert.match(r.out, new RegExp(`upgrade: multisig ${IDS.upgrade_multisig}, vault ${IDS.upgrade_authority}: the pinned addresses`));
  assert.match(r.out, new RegExp(`guardian: multisig ${IDS.guardian_multisig}, vault ${IDS.guardian}: the pinned addresses`));
  const json = run("derive", "--json", "--upgrade-create-key", FIXTURE.multisigs.upgrade.create_key, "--guardian-create-key", FIXTURE.multisigs.guardian.create_key);
  assert.deepEqual(JSON.parse(json.out), { upgrade: { multisig: IDS.upgrade_multisig, vault: IDS.upgrade_authority, pinned: true },
                                           guardian: { multisig: IDS.guardian_multisig, vault: IDS.guardian, pinned: true } });
});

test("derive: any other create key is not the pinned addresses, and the exit code says so", () => {
  const r = run("derive", "--upgrade-create-key", Keypair.generate().publicKey.toBase58(), "--guardian-create-key", FIXTURE.multisigs.guardian.create_key);
  assert.equal(r.code, 1);
  assert.match(r.out, /upgrade: .*: NOT the pinned addresses/);
  assert.match(r.out, /guardian: .*: the pinned addresses/);
});

test("create: a create key that gives other addresses is refused before anything is sent", () => {
  const r = run("create", "--member", Keypair.generate().publicKey.toBase58(), "--member", Keypair.generate().publicKey.toBase58(),
                "--upgrade-create-key", keyFile("upgrade-create-key.json"), "--guardian-create-key", keyFile("guardian-create-key.json"));
  assert.equal(r.code, 1);
  assert.match(r.err, /^refused: the upgrade create key \w+ gives multisig \w+ and vault \w+, but the programs pin multisig 9HcsMEo2o6zZu9t1kbFWpnyKn7hiHaZYYFwNHZSpmWqK/);
  assert.match(r.err, /This is not the upgrade create key: nothing was sent\.\n$/);
  assert.equal(r.out, "", "it said nothing about a cluster: it never connected");
});

test("create: a threshold nobody can meet, and a member given twice, are refused", () => {
  const a = Keypair.generate().publicKey.toBase58(), b = Keypair.generate().publicKey.toBase58();
  assert.match(run("create", "--member", a, "--member", b, "--threshold", "3").err, /a threshold of 3 cannot be met by 2 member\(s\)/);
  assert.match(run("create", "--member", a, "--member", a).err, /the same member key was given twice/);
  assert.match(run("create", "--member", a, "--member", b, "--threshold", "0").err, /a threshold of 0 cannot be met/);
});

test("guardian: the command line is checked before the cluster is asked anything", () => {
  const payer = keyFile("payer.json");
  assert.match(run("guardian", "pause", "604801", "--fee-payer", payer).err, /a pause lasts 0 to 604800 seconds/);
  assert.match(run("guardian", "pause", "soon", "--fee-payer", payer).err, /a pause lasts 0 to 604800 seconds/);
  assert.match(run("guardian", "approve", "0", "abc", "--fee-payer", payer).err, /the key hash is 64 lowercase hex characters/);
  assert.match(run("guardian", "revoke", "7", KEY_HASH, "--fee-payer", payer).err, /takes the issuer \(0 or github, 1 or gitlab\) and the key hash/);
  assert.match(run("guardian", "approve", "github", "--fee-payer", payer).err, /takes the issuer .* and the key hash/);
  assert.match(run("guardian", "mint", "--fee-payer", payer).err, /the guardian can do three things/);
  assert.match(run("guardian", "pause", "600", "--fee-payer", path.join(tmp, "missing.json")).err, /cannot read the keypair file .*missing\.json/);
  assert.match(run("guardian", "pause", "600", "--fee-payer", payer).err, /cannot reach the cluster at http:\/\/127\.0\.0\.1:9/, "a good command line reaches the network step");
});

test("upgrade and the votes refuse what cannot be understood, at once", () => {
  assert.match(run("upgrade", "propose", "knos_money", BUFFER).err, /upgrade takes knos_oidc, knos_pay, knos_meter or knos_passkey, then the address of the buffer/);
  assert.match(run("upgrade", "propose", "upgrade_gate", BUFFER).err, /upgrade takes knos_oidc, knos_pay, knos_meter or knos_passkey/);
  assert.match(run("upgrade", "propose", "knos_meter").err, /upgrade needs the buffer's address/);
  assert.match(run("upgrade", "propose", "knos_pay").err, /upgrade needs the buffer's address/);
  assert.match(run("upgrade", "sideways").err, /upgrade takes propose <knos_oidc\|knos_pay\|knos_meter\|knos_passkey> <buffer address>, or execute/);
  assert.match(run("approve", "treasury", "1").err, /give the multisig and the proposal: upgrade or guardian/);
  assert.match(run("execute", "upgrade", "first").err, /give the multisig and the proposal/);
  assert.match(run("upgrade", "execute", "3", "--expect-hash", "abc").err, /--expect-hash goes with an upgrade proposal and takes the build's executable hash: 64 lowercase hex/);
  assert.match(run("execute", "guardian", "3", "--expect-hash", "ab".repeat(32)).err, /--expect-hash goes with an upgrade proposal/);
  assert.match(run("frobnicate").err, /there is no command frobnicate\. Run node scripts\/governance\.mjs --help/);
});

test("inner: the instruction a proposal would carry, as JSON, is the Python client's", () => {
  const same = (args, want) => {
    const r = run("inner", ...args, "--fee-payer", PAYER);
    assert.equal(r.code, 0, r.err);
    const got = JSON.parse(r.out);
    assert.deepEqual({ program: got.program, data: got.data, accounts: got.accounts.map((a) => ({ pubkey: a.address, signer: a.signer, writable: a.writable })) }, want);
  };
  same(["guardian", "approve", "github", KEY_HASH], FIXTURE.instructions["guardian approve github"]);
  same(["guardian", "approve", "1", KEY_HASH], FIXTURE.instructions["guardian approve gitlab"]);
  same(["guardian", "revoke", "0", KEY_HASH], FIXTURE.instructions["guardian revoke github"]);
  same(["guardian", "revoke", "gitlab", KEY_HASH], FIXTURE.instructions["guardian revoke gitlab"]);
  same(["guardian", "pause", "600"], FIXTURE.instructions["guardian pause 600"]);
  same(["guardian", "pause", "0"], FIXTURE.instructions["guardian pause 0"]);
  same(["guardian", "pause", "604800"], FIXTURE.instructions["guardian pause 604800"]);
  same(["upgrade", "knos_pay", BUFFER, "--spill", SPILL], FIXTURE.instructions["upgrade knos_pay"]);
});

test("--help lists every command, and an empty command line does too", () => {
  for (const r of [run("--help"), run()]) {
    assert.equal(r.code, 0, r.err);
    for (const words of ["create", "show [--check]", "guardian approve <issuer> <key hash>", "guardian revoke", "guardian pause <seconds>", "upgrade propose",
                         "upgrade propose <knos_oidc|knos_pay|knos_meter|knos_passkey> <buffer address>",
                         "upgrade execute <index> [--expect-hash HASH]", "approve <upgrade|guardian> <index>", "cancel <upgrade|guardian> <index>", "derive"]) {
      assert.ok(r.out.includes(words), `the help says "${words}"`);
    }
  }
});

test("upgrade propose --out writes the proposal as data, and names no time until the proposal is approved", () => {
  const program = new web3.PublicKey(gov.IDS.knos_pay), buffer = web3.Keypair.generate().publicKey;
  const approved = gov.proposalRecord("knos_pay", program, buffer, "ab".repeat(32), 7n, 172_800, { status: { __kind: "Approved", timestamp: 1_790_000_000n } });
  assert.deepEqual(approved, { program: "knos_pay", address: gov.IDS.knos_pay, buffer: buffer.toBase58(), hash: "ab".repeat(32), index: 7, status: "Approved",
                               approved_at: 1_790_000_000, executable_from: 1_790_172_800 });
  const active = gov.proposalRecord("knos_pay", program, buffer, "ab".repeat(32), 7n, 172_800, { status: { __kind: "Active", timestamp: 1_790_000_000n } });
  assert.equal(active.executable_from, null);          // the 48 hours start with the last approval, not with the proposal
  assert.equal(active.approved_at, null);
});

// ---- 0.3.14: four programs, a proposal withdrawn, and a run that executes only the build it was arranged for ------------------
test("an upgrade can be proposed for each of the four programs the upgrade vault holds, and for nothing else", () => {
  assert.deepEqual(gov.PROGRAMS, ["knos_oidc", "knos_pay", "knos_meter", "knos_passkey"]);
  const vault = pk(IDS.upgrade_authority);
  for (const name of gov.PROGRAMS) {
    const r = run("inner", "upgrade", name, BUFFER, "--fee-payer", PAYER, "--spill", SPILL);
    assert.equal(r.code, 0, r.err);
    const got = JSON.parse(r.out);
    // the loader's Upgrade on THAT program: its program data, itself, the buffer; the vault signs
    assert.deepEqual([got.program, got.data, got.accounts[0].address, got.accounts[1].address, got.accounts[2].address],
                     [gov.LOADER.toBase58(), "03000000", gov.programData(pk(IDS[name])).toBase58(), IDS[name], BUFFER]);
    assert.deepEqual(got.accounts.filter((a) => a.signer).map((a) => a.address), [vault.toBase58()]);
  }
  assert.equal(new Set(gov.PROGRAMS.map((n) => IDS[n])).size, 4);
  assert.match(run("inner", "upgrade", "upgrade_gate", BUFFER, "--fee-payer", PAYER).err, /upgrade takes knos_oidc, knos_pay, knos_meter or knos_passkey/);
});

test("a proposal is withdrawn by the votes the Squads program takes for its state: cancel when approved, reject while it collects approvals", () => {
  const key = () => Keypair.generate().publicKey;
  const [a, b, c] = [key(), key(), key()];
  const ms = { threshold: 2, members: [a, b, c].map((k) => ({ key: k, permissions: { mask: 7 } })) };
  const p = (kind, more = {}) => ({ status: { __kind: kind, timestamp: 1_791_098_249n }, approved: [a, b], rejected: [], cancelled: [], ...more });
  // approved, inside its 48 hours or after them: `threshold` cancel votes (proposalCancel asks only for the status Approved)
  assert.deepEqual(gov.withdrawal(ms, p("Approved")), { how: "cancel", need: 2, done: [] });
  assert.deepEqual(gov.withdrawal(ms, p("Approved", { cancelled: [c] })), { how: "cancel", need: 2, done: [c.toBase58()] });
  // one vote short of approved: two of three reject it, and then two can no longer approve
  assert.deepEqual(gov.withdrawal(ms, p("Active", { approved: [a] })), { how: "reject", need: 2, done: [] });
  // a member who cannot vote does not count towards the cutoff
  const some = { threshold: 2, members: [...ms.members, { key: key(), permissions: { mask: 5 } }] };
  assert.equal(gov.withdrawal(some, p("Active")).need, 2);
  assert.equal(gov.withdrawal({ threshold: 3, members: ms.members }, p("Active")).need, 1);
  for (const kind of ["Draft", "Rejected", "Executing", "Executed", "Cancelled"]) assert.equal(gov.withdrawal(ms, p(kind)), null, kind);
  // the instructions exist in the SDK this repository pins, and take the member as a signer on the proposal's own account
  for (const name of ["proposalCancel", "proposalReject", "proposalApprove"]) {
    const ix = squads.instructions[name]({ multisigPda: pk(IDS.upgrade_multisig), transactionIndex: 2n, member: a });
    assert.equal(ix.programId.toBase58(), IDS.squads_program, name);
    assert.deepEqual(ix.keys.map((k) => [k.pubkey.toBase58(), k.isSigner]),
                     [[IDS.upgrade_multisig, false], [a.toBase58(), true], [squads.getProposalPda({ multisigPda: pk(IDS.upgrade_multisig), transactionIndex: 2n })[0].toBase58(), false]], name);
  }
  const src = fs.readFileSync(path.join(HERE, "governance.mjs"), "utf8");
  assert.match(src, /cancel: \["proposalCancel", "cancelled"\], reject: \["proposalReject", "rejected"\]/);
});

test("upgrade execute --expect-hash executes only the build the run was arranged for", () => {
  const want = FIXTURE.loader_accounts.buffer, buffer = pk(BUFFER);
  const info = { owner: gov.LOADER, data: Buffer.from(want.data, "hex") };
  assert.match(gov.expected(3n, buffer, info, want.executable_hash), new RegExp(`^proposal 3: its buffer ${BUFFER} holds the build ${want.executable_hash}, the one this run was arranged for$`));
  const refused = (b, i, h, words) => assert.throws(() => gov.expected(3n, b, i, h), (e) => e instanceof gov.Refused && words.test(e.message) && /Nothing was sent/.test(e.message));
  // the withdrawn build's hash against a proposal that carries another build
  refused(buffer, info, "69ec05b83e29b92fb255fd7f0cd52e128e04a4c9dbc5e16eecdc39caaafed9c9", new RegExp(`would deploy the build ${want.executable_hash}, and this run was arranged for the build 69ec05b8`));
  refused(buffer, null, want.executable_hash, /is not a program buffer on this cluster/);                         // closed
  refused(buffer, { ...info, owner: squads.PROGRAM_ID }, want.executable_hash, /is not a program buffer/);        // the same bytes in an account the loader does not own
  refused(buffer, { owner: gov.LOADER, data: Buffer.from(FIXTURE.loader_accounts.programdata.data, "hex") }, want.executable_hash, /is not a program buffer/);
  refused(null, null, want.executable_hash, /carries no upgrade of a program/);                                   // a config change, or a closed transaction
  // the buffer is read from the proposal's own transaction: the loader's Upgrade, third account
  const ix = gov.upgradeIx(pk(IDS.knos_pay), buffer, pk(IDS.upgrade_authority), pk(SPILL));
  const keys = [pk(IDS.upgrade_authority), ...ix.keys.map((k) => k.pubkey).filter((k) => !k.equals(pk(IDS.upgrade_authority))), gov.LOADER];
  const at = (k) => keys.findIndex((x) => x.equals(k));
  const message = (data, programId = gov.LOADER) => ({ accountKeys: keys, instructions: [{ programIdIndex: at(programId), accountIndexes: Uint8Array.from(ix.keys.map((k) => at(k.pubkey))), data }] });
  assert.equal(gov.upgradeBuffer(message(Uint8Array.from(ix.data))).toBase58(), BUFFER);
  assert.equal(gov.upgradeBuffer(message(Uint8Array.from([4, 0, 0, 0]))), null, "another instruction of the loader");
  assert.equal(gov.upgradeBuffer(message(Uint8Array.from(ix.data), pk(IDS.knos_pay))), null, "another program");
  assert.equal(gov.upgradeBuffer({ accountKeys: keys, instructions: [] }), null);
  // the check is before the execution, and the flag is one the command line takes
  const src = fs.readFileSync(path.join(HERE, "governance.mjs"), "utf8");
  const body = src.slice(src.indexOf("async function execute("), src.indexOf("// ---- no network"));
  assert.ok(body.indexOf("say(expected(") > 0 && body.indexOf("say(expected(") < body.indexOf("await executeProposal("), "the build is compared before anything is sent");
  assert.match(src, /"expect-hash": \{ type: "string" \}/);
});
