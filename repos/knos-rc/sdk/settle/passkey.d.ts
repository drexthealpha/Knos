// Types for passkey.js: a wallet whose only key is a WebAuthn passkey (knos-passkey), and the funding of a work order from it.

export type Address = string;
export type Bytes = Uint8Array;
export type Num = number | bigint;
export interface AccountMeta { pubkey: Address; signer: boolean; writable: boolean }
export interface Instruction { program: Address; data: Bytes; accounts: AccountMeta[] }
/** What a passkey returns for a signature: as `sign` gives it, or the response of navigator.credentials.get (ArrayBuffers). */
export interface AssertionParts { authenticatorData: Bytes | ArrayBuffer; clientDataJSON: Bytes | ArrayBuffer; signature: Bytes | ArrayBuffer }
export type Assertion = AssertionParts | { response: AssertionParts };
/** A P-256 public key: compressed (33 bytes), the 65-byte point, or the SubjectPublicKeyInfo getPublicKey() returns. */
export type PublicKey = Bytes | ArrayBuffer;

export const PASSKEY: Address;
export const SECP256R1: Address;
export const INSTRUCTIONS: Address;
export const TOKEN: Address;
export const TOKEN_2022: Address;
export const ATA_PROGRAM: Address;
export const SYSTEM: Address;
/** knos_pay, the second deployment: the program whose orders Fund funds. */
export const KNOS_PAY: Address;
export const WALLET_LEN: number;
/** knos_pay's tag of FundOrderWallet, and the fewest bytes its data has. */
export const FUND_ORDER_WALLET: number;
export const FUND_MIN: number;
/** The order of P-256. */
export const N: bigint;
export const ERRORS: Record<number, string>;

export function b58(raw: Bytes): Address;
export function unb58(s: Address, size?: number): Bytes;
export function sha256(b: Bytes): Promise<Bytes>;
export function b64url(raw: Bytes): string;
export function findProgramAddress(seeds: Bytes[], program: Address): Promise<[Address, number]>;
export function ata(owner: Address, mint: Address, tokenProgram?: Address): Promise<Address>;
export function createAtaIx(payer: Address, owner: Address, mint: Address, tokenProgram?: Address): Promise<Instruction>;

/** The key as the program takes it: 33 bytes starting with 02 or 03. */
export function compressed(publicKey: PublicKey): Bytes;
export function keyFromAuthenticatorData(authenticatorData: Bytes | ArrayBuffer): Bytes;
/** The compressed key of a credential navigator.credentials.create returned. */
export function publicKeyOf(credential: unknown): Bytes;
/** The address of a passkey's wallet. */
export function wallet(publicKey: PublicKey, program?: Address): Promise<Address>;
/** The 32 bytes the passkey signs to withdraw `amount` of `mint` to the token account `to`, as the wallet's number `nonce`. */
export function challenge(walletAddress: Address, mint: Address, to: Address, amount: Num, nonce: Num): Promise<Bytes>;
/** A wallet account's bytes; null when the wallet is not open yet (its next nonce is then 1). */
export function readWallet(raw: Bytes | null): { key: Bytes; nonce: Num } | null;
/** r then s, 32 bytes each, s in the lower half of the order; takes that form or the DER a browser returns. */
export function rawSignature(signature: Bytes | ArrayBuffer): Bytes;

export function openIx(payer: Address, publicKey: PublicKey, program?: Address): Promise<Instruction>;
export function secp256r1Ix(publicKey: PublicKey, signature: Bytes | ArrayBuffer, message: Bytes | ArrayBuffer): Instruction;
/** The precompile, then Withdraw: keep them adjacent and in this order. */
export function withdrawIxs(a: { key: PublicKey; mint: Address; to: Address; amount: Num; nonce: Num; assertion: Assertion; tokenProgram?: Address;
  from?: Address | null; program?: Address }): Promise<[Instruction, Instruction]>;

/** The 32 bytes the passkey signs to fund the order `data` describes (the whole instruction data of knos_pay's FundOrderWallet with
 *  the passkey wallet as funder), in `mint`, as the wallet's number `nonce`, in no slot after `expirySlot`. */
export function fundChallenge(mint: Address, data: Bytes, expirySlot: Num, nonce: Num, payProgram?: Address): Promise<Bytes>;
/** The address of the order a FundOrderWallet with this data creates when `walletAddress` is its funder. */
export function orderOf(walletAddress: Address, data: Bytes, payProgram?: Address): Promise<Address>;
/** The precompile, then Fund: keep them adjacent and in this order. Anyone pays the transaction's fee and the two accounts' rent. */
export function fundIxs(a: { key: PublicKey; mint: Address; data: Bytes; expirySlot: Num; nonce: Num; assertion: Assertion; tokenProgram?: Address;
  from?: Address | null; program?: Address; payProgram?: Address }): Promise<[Instruction, Instruction]>;

export const WITHDRAW_PREFIX: string;
export interface WithdrawRequest { key: PublicKey; mint: Address; to: Address; amount: Num; nonce: Num; assertion: Assertion }
/** The base64 text of a withdrawal request: the one line a relay reads. */
export function withdrawRequest(request: WithdrawRequest): string;
export function withdrawLine(request: WithdrawRequest): string;
export function readWithdrawRequest(text: string): { key: Bytes; mint: Address; to: Address; amount: bigint; nonce: bigint; authenticatorData: Bytes;
  clientDataJSON: Bytes; signature: Bytes } | null;

/** What to pass to navigator.credentials.create for a passkey this program can verify: ES256 (P-256) only. */
export function createOptions(a: { rpId: string; rpName?: string; userName: string; userId?: Bytes }): { publicKey: Record<string, unknown> };
/** Creates a passkey and says where its wallet is. `credentials`: navigator.credentials, or a stand-in. */
export function create(options: { rpId: string; rpName?: string; userName: string; userId?: Bytes }, credentials?: unknown): Promise<{ credentialId: Bytes; key: Bytes; wallet: Address }>;
/** Asks the passkey to sign `challenge` (32 bytes). */
export function sign(challenge: Bytes, a: { rpId: string; credentialId?: Bytes | null }, credentials?: unknown): Promise<{ authenticatorData: Bytes; clientDataJSON: Bytes; signature: Bytes }>;
