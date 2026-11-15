// node sdk/settle/passkey.test.mjs   (sdk/settle/test.mjs runs it too)
// passkey.js against the bytes the Python client built (passkey.fixtures.json, written by scripts/passkey_fixtures.py: tests/test_passkey_chain.py sends
// exactly those instructions to the program in LiteSVM, where the secp256r1 precompile verifies the signature), then
// a whole withdrawal with a P-256 key from node:crypto standing in for the authenticator and an object standing in
// for navigator.credentials. No browser, no network. Exit 1 on the first mismatch.
import { createHash, generateKeyPairSync, sign as ecSign, verify as ecVerify } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as knos from "./index.js";
import * as passkey from "./passkey.js";

const fx = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "passkey.fixtures.json"), "utf8"));
const i = fx.inputs;
let n = 0;
function same(name, got, want) {
  n++;
  const text = (v) => JSON.stringify(v, (_k, x) => (typeof x === "bigint" ? `${x}n` : x));
  if (text(got) !== text(want)) { console.error(`MISMATCH ${name}\n  got  ${text(got)}\n  want ${text(want)}`); process.exit(1); }
}
const throws = async (name, f) => { let threw = false; try { await f(); } catch { threw = true; } same(name, threw, true); };
const hex = (u8) => Buffer.from(u8).toString("hex"), unhex = (s) => Uint8Array.from(Buffer.from(s, "hex"));
const plain = (ix) => ({ program: ix.program, data: hex(ix.data), accounts: ix.accounts.map((a) => ({ pubkey: a.pubkey, signer: a.signer, writable: a.writable })) });
const sha = (b) => createHash("sha256").update(b).digest();

// ---- the fixtures ----------------------------------------------------------------------------------------------------
same("the program", passkey.PASSKEY, fx.program);
const key = passkey.compressed(unhex(i.spki));
same("the key, from getPublicKey()", hex(key), fx.key);
same("the key, from the point", hex(passkey.compressed(unhex(i.point))), fx.key);
same("the key, from itself", hex(passkey.compressed(key)), fx.key);
same("the key, from a registration's authenticator data", hex(passkey.keyFromAuthenticatorData(unhex(i.registration_authenticator_data))), fx.key);
same("the key, from a credential with getPublicKey", hex(passkey.publicKeyOf({ response: { getPublicKey: () => unhex(i.spki).buffer } })), fx.key);
same("the key, from a credential with getAuthenticatorData", hex(passkey.publicKeyOf({ response: { getAuthenticatorData: () => unhex(i.registration_authenticator_data).buffer } })), fx.key);
same("the key, from the attestation object alone", hex(passkey.publicKeyOf({ response: { attestationObject: unhex(i.attestation_object).buffer } })), fx.key);
for (const [name, bad] of [["too short", key.subarray(0, 32)], ["not a point", Uint8Array.of(5, ...key.subarray(1))], ["empty", new Uint8Array(0)]]) {
  await throws(`a key that is ${name} is refused`, () => passkey.compressed(bad));
}
await throws("authenticator data of a signature carries no key", () => passkey.keyFromAuthenticatorData(unhex(i.authenticator_data)));
same("the wallet", await passkey.wallet(unhex(i.spki)), fx.wallet);
same("the wallet's token account", await passkey.ata(fx.wallet, fx.mint), fx.from);
same("the destination", await passkey.ata(fx.owner, fx.mint), fx.to);
same("addresses as index.js derives them", [await knos.ata(fx.owner, fx.mint), (await knos.findProgramAddress([new TextEncoder().encode("pk"), sha(key)], fx.program))[0]], [fx.to, fx.wallet]);
same("the challenge", hex(await passkey.challenge(fx.wallet, fx.mint, fx.to, i.amount, i.nonce)), fx.challenge);
same("the challenge as the client data carries it", [passkey.b64url(unhex(fx.challenge)), JSON.parse(i.client_data_json).challenge], [fx.challenge_b64url, fx.challenge_b64url]);
same("a high s is lowered", hex(passkey.rawSignature(unhex(i.signature_der))), fx.raw_signature);
same("a raw signature stays", hex(passkey.rawSignature(unhex(fx.raw_signature))), fx.raw_signature);
for (const bad of [new Uint8Array(0), unhex(i.signature_der).subarray(1), new Uint8Array(64), new Uint8Array(64).fill(255)]) {
  await throws("what is not a signature is refused", () => passkey.rawSignature(bad));
}
const assertion = { authenticatorData: unhex(i.authenticator_data), clientDataJSON: new TextEncoder().encode(i.client_data_json), signature: unhex(i.signature_der) };
const built = await passkey.withdrawIxs({ key, mint: fx.mint, to: fx.to, amount: i.amount, nonce: i.nonce, assertion });
same("Open", plain(await passkey.openIx(fx.payer, unhex(i.spki))), fx.ixs.open);
same("the destination's token account", plain(await passkey.createAtaIx(fx.payer, fx.owner, fx.mint)), fx.ixs.create_ata);
same("the precompile instruction", plain(built[0]), fx.ixs.secp256r1);
same("Withdraw", plain(built[1]), fx.ixs.withdraw);
same("the same from a browser's response (ArrayBuffers)", (await passkey.withdrawIxs({ key, mint: fx.mint, to: fx.to, amount: i.amount, nonce: i.nonce,
  assertion: { response: { authenticatorData: assertion.authenticatorData.buffer, clientDataJSON: assertion.clientDataJSON.buffer, signature: assertion.signature.buffer } } })).map(plain),
  [fx.ixs.secp256r1, fx.ixs.withdraw]);
// ---- Fund (1.1): the bytes src/knos/settle/v2/passkey_fund.py built (fixtures.json: passkey_fund, from scripts/settle_fixtures.py) ----
const pf = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "fixtures.json"), "utf8")).second.passkey_fund, fi = pf.inputs;
same("the errors, in the Python client's words", passkey.ERRORS, { ...fx.errors, ...pf.errors });
{
  const fundKey = unhex(fi.key), data = unhex(fi.data), hidden = unhex(fi["data (private)"]);
  const signed = { authenticatorData: unhex(fi.authenticator_data), clientDataJSON: new TextEncoder().encode(fi.client_data_json), signature: unhex(fi.signature) };
  same("Fund: the orders it funds are knos_pay's, and the wallet is the passkey's", [passkey.KNOS_PAY, await passkey.wallet(fundKey)], [pf.pay, pf.wallet]);
  same("Fund: constants", { FUND_ORDER_WALLET: passkey.FUND_ORDER_WALLET, FUND_MIN: passkey.FUND_MIN }, pf.constants);
  same("Fund: the challenge", hex(await passkey.fundChallenge(fi.mint, data, fi.expiry_slot, fi.nonce)), pf.challenge);
  same("Fund: another amount, mint, expiry or nonce has another challenge", new Set([pf.challenge, hex(await passkey.fundChallenge(fi.mint22, data, fi.expiry_slot, fi.nonce)),
    hex(await passkey.fundChallenge(fi.mint, hidden, fi.expiry_slot, fi.nonce)), hex(await passkey.fundChallenge(fi.mint, data, fi.expiry_slot + 1, fi.nonce)),
    hex(await passkey.fundChallenge(fi.mint, data, fi.expiry_slot, fi.nonce + 1))]).size, 5);
  same("Fund: the order of a public funding, and of a private one", [await passkey.orderOf(pf.wallet, data), await passkey.orderOf(pf.wallet, hidden)], [pf.order, pf["order (private)"]]);
  const k2 = knos.v2.client({ knos_pay: pf.pay });
  same("Fund: the order is the one index.js derives for the wallet as funder", await k2.orderPda(await knos.v2.scopeOf(new DataView(data.buffer).getBigUint64(9, true),
    new DataView(data.buffer).getBigUint64(1, true)), pf.wallet, new DataView(data.buffer).getUint32(34, true)), pf.order);
  const args = { key: fundKey, mint: fi.mint, data, expirySlot: fi.expiry_slot, nonce: fi.nonce, assertion: signed };
  same("Fund: the precompile, then Fund", (await passkey.fundIxs(args)).map(plain), pf.ixs);
  same("Fund: a private order, Token-2022, a token account given", (await passkey.fundIxs({ ...args, mint: fi.mint22, data: hidden, tokenProgram: passkey.TOKEN_2022, from: fi.from })).map(plain),
    pf["ixs (private, token-2022, a token account given)"]);
  await throws("Fund: data that is not a FundOrderWallet's is refused", () => passkey.fundIxs({ ...args, data: Uint8Array.of(16, ...data.subarray(1)) }));
  await throws("Fund: data cut short is refused", () => passkey.orderOf(pf.wallet, data.subarray(0, 157)));
}
// the withdrawal request a relay reads: the same text, and the same line, as the Python relay's own writer makes
const asked = { key, mint: fx.mint, to: fx.to, amount: i.amount, nonce: i.nonce, assertion };
same("the withdrawal request", passkey.withdrawRequest(asked), fx.request);
same("the line the site shows for it", passkey.withdrawLine(asked), fx.request_line);
same("the line starts with the marker the relay looks for", fx.request_line, `${passkey.WITHDRAW_PREFIX} ${fx.request}`);
same("the same request from the spki and a browser's response", passkey.withdrawRequest({ ...asked, key: unhex(i.spki), assertion: { response: assertion } }), fx.request);
for (const text of [fx.request, fx.request_line, ` ${fx.request_line}\n`, fx.request.replace(/\+/g, "-").replace(/\//g, "_")]) {
  const back = passkey.readWithdrawRequest(text);
  same("the request read back", { ...back, key: hex(back.key), authenticatorData: hex(back.authenticatorData), clientDataJSON: new TextDecoder().decode(back.clientDataJSON),
    signature: hex(back.signature) }, { key: fx.key, mint: fx.mint, to: fx.to, amount: BigInt(i.amount), nonce: BigInt(i.nonce),
    authenticatorData: i.authenticator_data, clientDataJSON: i.client_data_json, signature: fx.raw_signature });
  same("and it builds the same two instructions", (await passkey.withdrawIxs({ ...back, assertion: back })).map(plain), [fx.ixs.secp256r1, fx.ixs.withdraw]);
}
for (const bad of ["", "knos-withdraw:", "knos-withdraw: !!!", `${fx.request}AAAA`, fx.request.slice(0, -8), "/knos address x", null]) {
  same("what is not a request reads as none", passkey.readWithdrawRequest(bad), null);
}
const tx = knos.serializeTx([await passkey.openIx(fx.payer, key), await passkey.createAtaIx(fx.payer, fx.owner, fx.mint), ...built], fx.payer, knos.SYSTEM);
same("opening, creating the destination and withdrawing fit one transaction", tx.length <= 1232, true);
const account = unhex(fx.account.data);
same("a wallet account", [hex(passkey.readWallet(account).key), passkey.readWallet(account).nonce], [fx.account.key, fx.account.nonce]);
same("an account that is not a wallet", [passkey.readWallet(null), passkey.readWallet(new Uint8Array(48)), passkey.readWallet(account.subarray(1))], [null, null, null]);

// ---- a passkey from node:crypto, behind a stand-in for navigator.credentials -------------------------------------------
// What a platform authenticator does: creates a P-256 key, and signs authenticatorData || sha256(clientDataJSON) in DER.
const RP = "knos.dev";
function authenticator() {
  const made = [];
  const clientData = (type, challenge) => new TextEncoder().encode(JSON.stringify({ type, challenge: passkey.b64url(new Uint8Array(challenge)), origin: `https://${RP}`, crossOrigin: false }));
  return { made,
    async create({ publicKey }) {
      same("a P-256 key is asked for, and nothing else", publicKey.pubKeyCredParams, [{ type: "public-key", alg: -7 }]);
      const pair = generateKeyPairSync("ec", { namedCurve: "P-256" });
      const spki = pair.publicKey.export({ type: "spki", format: "der" });
      made.push(pair);
      return { rawId: Uint8Array.of(made.length).buffer, response: { getPublicKey: () => spki.buffer.slice(spki.byteOffset, spki.byteOffset + spki.length),
        clientDataJSON: clientData("webauthn.create", publicKey.challenge).buffer } };
    },
    async get({ publicKey }) {
      const pair = made[new Uint8Array(publicKey.allowCredentials[0].id)[0] - 1];
      const authenticatorData = Buffer.concat([sha(RP), Buffer.from([0x05, 0, 0, 0, 1])]);
      same("the assertion is asked for this site", publicKey.rpId, RP);
      const clientDataJSON = clientData("webauthn.get", publicKey.challenge);
      const signature = ecSign("sha256", Buffer.concat([authenticatorData, sha(clientDataJSON)]), pair.privateKey);    // DER, either s
      return { response: { authenticatorData: authenticatorData.buffer.slice(authenticatorData.byteOffset, authenticatorData.byteOffset + authenticatorData.length),
        clientDataJSON: clientDataJSON.buffer, signature: signature.buffer.slice(signature.byteOffset, signature.byteOffset + signature.length) } };
    } };
}
const device = authenticator();
for (let round = 0; round < 8; round++) {            // several keys and signatures: both parities of y, both halves of s
  const made = await passkey.create({ rpId: RP, rpName: "Knos", userName: "octocat" }, device);
  const spki = device.made.at(-1).publicKey.export({ type: "spki", format: "der" });
  same("create: the key is the one the authenticator made", [made.key.length, hex(made.key.subarray(1)), 2 + (spki[90] & 1)], [33, hex(spki.subarray(27, 59)), made.key[0]]);
  same("create: the wallet is that key's", made.wallet, await passkey.wallet(spki));
  const amount = 5_000_000 + round, nonce = round + 1;
  const challenge = await passkey.challenge(made.wallet, fx.mint, fx.to, amount, nonce);
  const signed = await passkey.sign(challenge, { rpId: RP, credentialId: made.credentialId }, device);
  const [verify, withdraw] = await passkey.withdrawIxs({ key: made.key, mint: fx.mint, to: fx.to, amount, nonce, assertion: signed });
  // the precompile instruction, read back as the program reads it
  const d = verify.data, u16 = (k) => d[2 + 2 * k] | (d[3 + 2 * k] << 8);
  same("one signature, every part in the instruction itself", [d[0], u16(1), u16(3), u16(6)], [1, 0xFFFF, 0xFFFF, 0xFFFF]);
  const sig = d.subarray(u16(0), u16(0) + 64), message = d.subarray(u16(4), u16(4) + u16(5));
  same("the key the precompile checks is the wallet's", hex(d.subarray(u16(2), u16(2) + 33)), hex(made.key));
  same("the message ends where the data ends", u16(4) + u16(5), d.length);
  same("s is in the lower half", BigInt("0x" + hex(sig.subarray(32))) <= passkey.N / 2n, true);
  same("the signature verifies over the message, under that key", ecVerify("sha256", message, { key: device.made.at(-1).publicKey, dsaEncoding: "ieee-p1363" }, sig), true);
  // Withdraw's data, read back as the program reads it
  const w = withdraw.data, clientData = w.subarray(17), view = new DataView(w.buffer, w.byteOffset);
  same("Withdraw says the amount and the nonce", [w[0], view.getBigUint64(1, true), view.getBigUint64(9, true)], [1, BigInt(amount), BigInt(nonce)]);
  same("the message is authenticatorData || sha256(clientDataJSON)", hex(message), hex(Buffer.concat([Buffer.from(signed.authenticatorData), sha(clientData)])));
  const said = JSON.parse(new TextDecoder().decode(clientData));
  same("the client data is a signature's, over this withdrawal's challenge", [said.type, said.challenge], ["webauthn.get", passkey.b64url(challenge)]);
  same("a person was present", message[32] & 1, 1);
  same("the accounts: the wallet, its token account, the mint, the destination, the token program, the instructions sysvar",
    withdraw.accounts.map((a) => [a.pubkey, a.signer, a.writable]),
    [[made.wallet, false, true], [await passkey.ata(made.wallet, fx.mint), false, true], [fx.mint, false, false], [fx.to, false, true],
      [passkey.TOKEN, false, false], [passkey.INSTRUCTIONS, false, false]]);
  same("another amount, destination or nonce has another challenge", new Set([hex(challenge), hex(await passkey.challenge(made.wallet, fx.mint, fx.to, amount + 1, nonce)),
    hex(await passkey.challenge(made.wallet, fx.mint, fx.from, amount, nonce)), hex(await passkey.challenge(made.wallet, fx.mint, fx.to, amount, nonce + 1))]).size, 4);
}
{
  // every export has a declaration, and nothing is declared that is not there
  const dts = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "passkey.d.ts"), "utf8");
  const declared = [...dts.matchAll(/^export (?:const|function) (\w+)/gm)].map((m) => m[1]).sort();
  same("passkey.d.ts declares what passkey.js exports", declared, Object.keys(passkey).sort());
}
await throws("no passkeys in this browser", () => passkey.create({ rpId: RP, userName: "octocat" }, null));
await throws("no passkeys in this browser, signing", () => passkey.sign(new Uint8Array(32), { rpId: RP }, null));

console.log(`sdk/settle/passkey: ${n} checks (the Python client's bytes, and a withdrawal signed by a node:crypto P-256 key)`);
