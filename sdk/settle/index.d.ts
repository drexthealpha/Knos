// Types for knos-settle (sdk/settle/index.js). Everything index.js exports is declared here, and sdk/settle/test.mjs
// fails when an export, a member of `v2` or `meter`, or a method of a client has no declaration.
//
// Amounts, GitHub ids and times are `number`, or `bigint` past 2^53 (they never are for ids and real amounts).
// Addresses are base58 text. Hashes and scopes are lowercase hex text unless a function says Uint8Array.

export type Address = string;
export type Num = number | bigint;
export type Bytes = Uint8Array;

/** One account of an instruction. */
export interface AccountMeta { pubkey: Address; signer: boolean; writable: boolean }
/** An instruction as every builder here returns it, and as serializeTx and serializeTxV1 take it. */
export interface Instruction { program: Address; data: Bytes; accounts: AccountMeta[] }

/** src/knos/settle/v2/program_ids.json (and, for the first deployment, src/knos/settle/program_ids.json). */
export interface ProgramIds { knos_oidc: Address; knos_pay: Address; knos_meter?: Address; knos_passkey?: Address; [more: string]: unknown }

// ---- constants --------------------------------------------------------------------------------------------------------
export const TOKEN: Address;
export const TOKEN_2022: Address;
export const ATA_PROGRAM: Address;
export const SYSTEM: Address;
export const LOADER: Address;
export const SQUADS: Address;
export const FEE_OWNER: Address;
export const USDC_DEVNET: Address;
export const USDC_MAINNET: Address;
export const MERGE: 0;
export const TESTS: 1;
export const FEE_BPS: number;
export const FEE_MIN: number;
export const MIN_AMOUNT: number;
export const MAX_AMOUNT: number;
export const JOB_LEN: number;
export const DUE_LEN: number;
export const REP_LEN: number;
export const GITHUB: 0;
export const GITLAB: 1;
export const ISSUERS: Record<number, string>;
export const JWKS: Record<number, string>;
export const MAX_JWT: number;
export const LATE: number;
export const T_JWT: number;
export const CHUNK: number;
export const V1_PREFIX: 0x81;
export const V1_MAX_SIZE: number;
export const V1_MAX_ACCOUNTS: number;
export const V1_MAX_SIGNATURES: number;
export const V1_MAX_INSTRUCTIONS: number;
export const V1_HEAP: { min: number; max: number };

// ---- bytes, addresses ---------------------------------------------------------------------------------------------------
export function b58(bytes: Bytes): string;
export function unb58(text: string, size?: number): Bytes;
/** A Solana address: base58 that decodes to exactly 32 bytes, written the one way those bytes are written. */
export function isAddress(text: unknown): text is Address;
export function hex(bytes: Bytes): string;
export function unhex(text: string): Bytes;
export function u64le(value: Num): Bytes;
export function sha256(bytes: Bytes): Promise<Bytes>;
export function onCurve(bytes: Bytes): boolean;
export function findProgramAddress(seeds: Bytes[], program: Address | Bytes): Promise<[Address, number]>;
/** The owner's associated token account of a mint (`tokenProgram`: TOKEN, or TOKEN_2022 for a Token-2022 mint). */
export function ata(owner: Address | Bytes, mint: Address | Bytes, tokenProgram?: Address): Promise<Address>;
export function programData(program: Address | Bytes): Promise<Address>;

// ---- the first deployment ------------------------------------------------------------------------------------------------
export function fundAudience(issue: Num, amount: Num, mode?: number, checksHex?: string, workS?: number, reviewS?: number): string;
export function payAudience(repoId: Num, issue: Num, authorId: Num, headSha: string, checksHex?: string, mode?: number): string;
export function vetoAudience(repoId: Num, issue: Num): string;
export function claimAudience(address: Address): string;
/** The fee on a payment: 2.5%, at least 0.05, never more than the amount. The same in both deployments. */
export function feeOf(amount: Num): number;
export function wfRepoHash(repository: string): Promise<Bytes>;
export interface Job1 {
  state: string; mode: number; tokenFunded: boolean; repoId: Num; issue: Num; amount: Num; deadline: Num; review: Num; payAfter: Num; authorId: Num;
  funderId: Num; notBefore: Num; vetoes: number; funder: Address; mint: Address; checks: string; wfRepoHash: string; wfSha: string;
}
export function parseJob(raw: Bytes | null): Job1 | null;
export function parseDue(raw: Bytes | null): { amount: Num; userId: Num; mint: Address } | null;
export function parseRep(raw: Bytes | null): { paidJobs: number; totalPaid: Num; repositories: number };

export interface FundIxArgs {
  funder: Address; funderToken: Address; mint: Address; repoId: Num; issue: Num; amount: Num; wfRepo: string; wfSha: string;
  mode?: number; checksHex?: string; workS?: number; reviewS?: number;
}
export interface Client1 {
  ids: ProgramIds;
  oidc: Verifier;
  auth(): Promise<Address>;
  vault(mint: Address): Promise<Address>;
  faucetMint(): Promise<Address>;
  job(repoId: Num, issue: Num, funder?: Address | null): Promise<Address>;
  due(userId: Num, mint: Address): Promise<Address>;
  rep(userId: Num): Promise<Address>;
  rate(repoId: Num): Promise<Address>;
  fundIx(args: FundIxArgs): Promise<Instruction>;
  vetoIx(wallet: Address, job: Address): Instruction;
}
/** A client bound to the first deployment's program ids. */
export function client(ids: ProgramIds): Client1;

// ---- who can change a program --------------------------------------------------------------------------------------------
/** The upgrade authority in a program-data account: an address, null when the program is immutable, undefined when the
 *  bytes are not a program-data account (the program is not deployed). */
export function upgradeAuthority(programDataBytes: Bytes | null): Address | null | undefined;
export function squadsVault(multisig: Address, index?: number): Promise<Address>;
export interface Multisig {
  createKey: Address; configAuthority: Address; threshold: number; timeLock: number; transactionIndex: Num; staleTransactionIndex: Num;
  rentCollector: Address | null; members: { key: Address; permissions: number }[];
}
export function readMultisig(raw: Bytes | null): Multisig | null;

// ---- knos-oidc: the verifier ----------------------------------------------------------------------------------------------
export function tokenId(jwt: string | Bytes): Promise<Bytes>;
export function modulusBytes(n: Num): Bytes;
export function keyHash(n: Num): Promise<Bytes>;
export function keyParams(n: Num): { n0inv: number; r2: Bytes };
export function stepPlan(bits: number): number[];
/** What names an issuer on chain: sha256 of its URL, exactly as the issuer writes it in `iss`. */
export function issuerHash(url: string): Promise<Bytes>;
/** `issuer` is GitHub (0), GitLab (1), or any other RS256 issuer's URL. */
export function rotateAudience(issuer: number | string, n: Num): Promise<string>;
export function jwksKeys(jwks: { keys?: Record<string, unknown>[] }): [string, bigint][];
export interface Token { stage: number; issuer: number; done: number; exp: Num; key: Address; payer: Address; payload: Bytes; verified: boolean; claims(): Record<string, unknown> }
export function readToken(raw: Bytes | null): Token | null;

/** The verifier at one program id: its addresses and instructions. `tid` is tokenId(jwt); `n` a modulus. */
export interface Verifier {
  program: Address;
  tokenPda(payer: Address, tid: Bytes): Promise<Address>;
  /** The key account of GitHub (0) or GitLab (1), of any other issuer named by its URL, or (with `registrant`) the private key that wallet registered. */
  keyPda(issuer: number | string, n: Num, registrant?: Address | null): Promise<Address>;
  /** The account that holds an issuer's URL, created with its first key. */
  issPda(url: string): Promise<Address>;
  writeIxs(payer: Address, tid: Bytes, jwt: string | Bytes): Promise<Instruction[]>;
  stepIx(payer: Address, tid: Bytes, keyAccount: Address, squarings: number): Promise<Instruction>;
  closeIx(payer: Address, tid: Bytes): Promise<Instruction>;
  registerKeyIx(payer: Address, issuer: number, n: Num, attest?: Address | null, attestKey?: Address | null): Promise<Instruction>;
  registerIssuerKeyIx(payer: Address, url: string, n: Num, attest: Address, attestKey: Address): Promise<Instruction>;
  registerPrivateKeyIx(registrant: Address, url: string, n: Num): Promise<Instruction>;
  keyParamsIx(payer: Address, issuer: number | string, n: Num, registrant?: Address | null): Promise<Instruction>;
  refreshIx(payer: Address, issuer: number | string, n: Num, attest: Address, attestKey?: Address | null): Promise<Instruction>;
  approveIx(guardian: Address, issuer: number | string, n: Num): Promise<Instruction>;
  revokeIx(guardian: Address, issuer: number | string, n: Num, registrant?: Address | null): Promise<Instruction>;
}
export function verifier(program: Address): Verifier;

// ---- SPL Token ---------------------------------------------------------------------------------------------------------------
export function createAtaIx(payer: Address, owner: Address, mint: Address, tokenProgram?: Address): Promise<Instruction>;
export function transferCheckedIx(source: Address, mint: Address, dest: Address, owner: Address, amount: Num, decimals: number, tokenProgram?: Address): Instruction;
export function readMint(raw: Bytes | null): { decimals: number; supply: Num; mintAuthority: Address | null } | null;
export function readTokenAccount(raw: Bytes | null): { mint: Address; owner: Address; amount: Num } | null;

// ---- the second deployment: records ----------------------------------------------------------------------------------------------
export interface Job {
  state: string; mode: number; fromBalance: boolean; tokenProgram: Address; faucet: boolean; repoId: Num; issue: Num; amount: Num; deadline: Num;
  holdUntil: Num; payeeId: Num; funderId: Num; notBefore: Num; ownerId: Num; source: Address; refundTo: Address; rentTo: Address; mint: Address;
  terms: string; wfRepoHash: string; wfSha: string;
  /** Who the record counts as the funder: the Balance's GitHub owner id, or the funding wallet. */
  funder: Num | Address;
}
export interface Balance {
  faucet: boolean; ownerId: Num; authority: Address; mint: Address; capPerJob: Num; lastIat: Num; spenders: Num[]; spent: Num;
  /** It has a side account (balxPda) that every funding from it must pass. */
  hasX: boolean;
}
export interface Bind { userId: Num; wallet: Address; iat: Num }
export interface Standing { paid: number; funders: number; total: Num; testPaid: number; selfPaid: number; testTotal: Num; first: Num; last: Num }
export interface Order {
  state: "open" | "held" | "warranty" | "?"; mode: number; fromBalance: boolean; flags: number; decimals: number; reserveDays: number;
  /** 0 for a private order. */
  repoId: Num; issue: Num; scope: string; seq: number; holdbackBps: number; killBps: number;
  /** What the payees receive in total. */
  amount: Num;
  /** Escrowed on top of the amount. */
  fee: Num; rate: Num; paid: Num; deadline: Num; notBefore: Num; holdUntil: Num; warrantyS: Num; reservedBy: Num; reservedUntil: Num; cancelAt: Num;
  payeeId: Num; funderId: Num; ownerId: Num; arbiterId: Num; judgeRepoId: Num; source: Address; refundTo: Address; rentTo: Address; mint: Address;
  terms: string; wfRepoHash: string; wfSha: string; feeBps: number;
  tokenProgram: Address; faucet: boolean;
  /** Who the record counts as the funder: the Balance's GitHub owner id, or the funding wallet. */
  funder: Num | Address;
}
export interface Balx { dayLimit: Num; totalLimit: Num; repos: Num[]; wfSha: string; day: Num; daySpent: Num; totalSpent: Num }
export interface Plan { feeBps: number; ownerId: Num; expires: Num }
/** The record of a holdback: who paid its rent, the end of the warranty, and [GitHub id, wallet, amount] for each payee. */
export interface Holdback { payer: Address; until: Num; payees: [Num, Address, Num][] }
/** A marker: [who paid its rent, the time after which a used marker can be closed], or for a standing order's marker of a pull request [who paid its rent, its order]. */
export type Marker = [Address, Num] | [Address, Address];
export interface Key {
  state: number; issuer: number; bits: number; activeAt: Num; expiresAt: Num; approved: boolean; revoked: boolean; genesis: boolean;
  /** sha256 of the issuer's URL (hex), for a key of an issuer that is not GitHub (0) or GitLab (1). */
  issuerHash: string | null;
  private: boolean;
  /** The wallet that registered a private key. */
  registrant: Address | null;
}
/** A payee: GitHub id, basis points, address or null. */
export type Payee = [Num, number, Address | null];
/** A payee as pay_order takes it: [GitHub id, wallet or null (held), token account (optional)]. */
export type PayeeAccounts = [Num, Address | null] | [Num, Address | null, Address | null];
export interface ExplainedInstruction {
  program: string; address: Address; name: string; args: Record<string, unknown>; accounts: (AccountMeta & { name: string })[];
}
export interface OrderOptions {
  flags?: number; holdbackBps?: number; warrantyDays?: number; killBps?: number; reserveDays?: number; rate?: Num; arbiterId?: Num; judgeRepoId?: Num; salted?: boolean;
}

export interface V2Client {
  ids: ProgramIds;
  oidc: Verifier;
  auth(): Promise<Address>;
  vault(mint: Address): Promise<Address>;
  balance(ownerId: Num, authority: Address, mint: Address): Promise<Address>;
  faucetMint(): Promise<Address>;
  faucetBalance(ownerId: Num): Promise<Address>;
  baltok(balance: Address): Promise<Address>;
  job(repoId: Num, issue: Num, source: Address): Promise<Address>;
  bind(userId: Num): Promise<Address>;
  rep(userId: Num): Promise<Address>;
  pair(payeeId: Num, funder: Num | Address): Promise<Address>;
  rate(repoId: Num): Promise<Address>;
  pause(): Promise<Address>;
  /** A work order. `scope` is scopeOf(...) (bytes or hex), `source` the Balance it is funded from or the funding wallet, `seq` the funder's own counter. */
  orderPda(scope: Bytes | string, source: Address, seq?: number): Promise<Address>;
  /** The token account that holds one order's money and nothing else. */
  ovPda(order: Address): Promise<Address>;
  /** A Balance's side account. */
  balxPda(balance: Address): Promise<Address>;
  planPda(ownerId: Num): Promise<Address>;
  /** Where the holdback of an order in warranty goes. */
  hbPda(order: Address): Promise<Address>;
  /** Exists once a standing order has paid this pull request. */
  donePda(order: Address, pr: Num): Promise<Address>;
  /** The wallet an order pays for this payee instead of the payee's own. */
  assignPda(order: Address, payeeId: Num): Promise<Address>;
  /** The marker of a token that works once. `token`: the JWT, the data of its token account, or the 32 bytes sigHash gave. */
  usedPda(token: string | Bytes): Promise<Address>;

  openBalanceIx(a: { authority: Address; ownerId: Num; mint: Address; cap?: Num; spenders?: Num[]; tokenProgram?: Address }): Promise<Instruction>;
  setBalanceIx(a: { authority: Address; balance: Address; cap?: Num; spenders?: Num[] }): Instruction;
  withdrawIx(a: { authority: Address; balance: Address; mint: Address; amount?: Num; destToken?: Address | null; tokenProgram?: Address }): Promise<Instruction>;
  fundBalanceIx(a: { relayer: Address; fundToken: Address; key: Address; balance: Address; mint: Address; repoId: Num; issue: Num; terms: Bytes | string;
    tokenProgram?: Address; balx?: boolean }): Promise<Instruction>;
  fundWalletIx(a: { funder: Address; funderToken: Address; mint: Address; repoId: Num; issue: Num; amount: Num; wfRepo: string; wfSha: string; terms: Bytes | string;
    mode?: number; workS?: number; tokenProgram?: Address }): Promise<Instruction>;
  payoutAccounts(job: Address, j: Job, payeeId: Num, wallet: Address | null, destToken: Address | null): Promise<AccountMeta[]>;
  /** `used`: the token's single-use marker (usedPda), or what usedPda takes: a pay token pays, or holds, exactly one job. */
  payIx(a: { relayer: Address; payToken: Address; key: Address; job: Address; j: Job; payeeId: Num; wallet: Address | null; destToken?: Address | null;
    used: Address | string | Bytes }): Promise<Instruction>;
  settleIx(a: { relayer: Address; job: Address; j: Job; wallet: Address; destToken?: Address | null }): Promise<Instruction>;
  refundIx(a: { relayer: Address; job: Address; j: Job; refundToken?: Address | null }): Promise<Instruction>;
  bindIx(a: { relayer: Address; bindToken: Address; key: Address; userId: Num }): Promise<Instruction>;
  pauseIx(a: { guardian: Address; payer: Address; seconds: number }): Promise<Instruction>;
  initFaucetIx(a: { payer: Address }): Promise<Instruction>;
  faucetOpenIx(a: { relayer: Address; fundToken: Address; key: Address; ownerId: Num; repoId: Num }): Promise<Instruction>;

  /** The 2.1 build logs `knos2:version 1` when this is simulated; a 2.0 build refuses the instruction. */
  versionIx(): Instruction;
  /** The wallet that opened a Balance sets its side account. Limits are in the mint's smallest units (0: none). */
  setBalanceXIx(a: { authority: Address; balance: Address; dayLimit?: Num; totalLimit?: Num; repos?: Num[]; wfSha?: string }): Promise<Instruction>;
  /** FEE_OWNER sets the fee rate (50..=250 basis points) of the orders of one repository owner until `expires`. */
  setPlanIx(a: { feeOwner: Address; payer: Address; ownerId: Num; feeBps: number; expires: Num }): Promise<Instruction>;
  /** A wallet funds an order for an issue of any public repository: `amount` for the payees plus orderFee(amount) on top. */
  fundOrderWalletIx(a: { funder: Address; funderToken: Address; mint: Address; repoId: Num; issue: Num; amount: Num; wfRepo: string; wfSha: string;
    terms: Bytes | string; mode?: number; workS?: number; seq?: number; options?: Bytes | null; scope?: Bytes | string | null; tokenProgram?: Address }): Promise<Instruction>;
  fundOrderBalanceIx(a: { relayer: Address; fundToken: Address; key: Address; balance: Address; mint: Address; ownerId: Num; repoId: Num; issue: Num;
    terms: Bytes | string; used: Address | string | Bytes; seq?: number; tokenProgram?: Address }): Promise<Instruction>;
  orderCommon(relayer: Address, order: Address, o: Order, tipToken: Address | null): Promise<AccountMeta[]>;
  payeeAccounts(o: Order, payeeId: Num, wallet: Address | null, destToken: Address | null): Promise<AccountMeta[]>;
  /** The token is any judge's of the order, or its arbiter's ruling. `pr`: the pull request the audience names (a STANDING order marks it). */
  payOrderIx(a: { relayer: Address; payToken: Address; key: Address; order: Address; o: Order; payees: PayeeAccounts[]; tipToken?: Address | null; pr?: Num }): Promise<Instruction>;
  /** What PayOrder takes after its payees: each payee's assignment, then a standing order's marker or a holdback's record. */
  termsAccounts(order: Address, o: Order, payeeIds: Num[], pr: Num): Promise<AccountMeta[]>;
  settleOrderIx(a: { relayer: Address; order: Address; o: Order; wallet: Address; destToken?: Address | null; tipToken?: Address | null }): Promise<Instruction>;
  /** `killToken`: with a kill fee due (killFee(o) > 0), a token account of the taker's bound wallet; without it the fee stays held for him in the order. */
  refundOrderIx(a: { relayer: Address; order: Address; o: Order; refundToken?: Address | null; killToken?: Address | null }): Promise<Instruction>;
  topUpIx(a: { signer: Address; order: Address; o: Order; add: Num; fromToken?: Address | null }): Promise<Instruction>;

  /** Funds a PRIVATE order from a Balance: the data is the order's scope and its terms hash (bytes or hex each). */
  fundPrivateOrderBalanceIx(a: { relayer: Address; fundToken: Address; key: Address; balance: Address; mint: Address; ownerId: Num; scope: Bytes | string;
    termsHash: Bytes | string; used: Address | string | Bytes; seq?: number; tokenProgram?: Address }): Promise<Instruction>;
  /** Binds an organisation's wallet: `orgId` is the token's repository_owner_id. */
  bindOrgIx(a: { relayer: Address; bindToken: Address; key: Address; orgId: Num }): Promise<Instruction>;
  /** After the warranty, anyone: the holdback to the recorded wallets, the tip to the relayer, the rest of the fee to FEE_OWNER. */
  releaseIx(a: { relayer: Address; order: Address; o: Order; hb: Holdback; tipToken?: Address | null }): Promise<Instruction>;
  /** Inside the warranty, on a revert token of one of the order's judges (a, b or c): everything the order holds back to its funder. */
  revertIx(a: { relayer: Address; revertToken: Address; key: Address; order: Address; o: Order; hb: Holdback; refundToken?: Address | null }): Promise<Instruction>;
  /** Reserves an order for the taker a take token names. */
  reserveIx(a: { relayer: Address; takeToken: Address; key: Address; order: Address }): Instruction;
  /** Gives notice. A wallet's order: the funding wallet signs. A Balance's order: `cancelToken` and its `key`. */
  cancelIx(a: { signer: Address; order: Address; cancelToken?: Address | null; key?: Address | null }): Instruction;
  /** This order's payment for `payeeId` goes to the wallet `to`. */
  assignIx(a: { signer: Address; order: Address; payeeId: Num; to: Address }): Promise<Instruction>;
  /** Closes a used marker once its time has passed, or a pull request's marker once its `order` is closed. */
  closeMarkerIx(a: { marker: Address; rentTo: Address; order?: Address | null }): Instruction;

  /** What an instruction is, read back from its own bytes, for a person to check before signing. */
  explain(ix: Instruction): ExplainedInstruction;
}

export interface V2 {
  readonly MERGE: 0; readonly TESTS: 1; readonly FEE_BPS: number; readonly FEE_MIN: number; readonly MIN_AMOUNT: number; readonly MAX_AMOUNT: number;
  readonly FAUCET_CAP: number; readonly MIN_WORK: number; readonly MAX_WORK: number; readonly HOLD: number; readonly PAUSE_MAX: number; readonly FUND_PERIOD: number;
  readonly CLOCK_SLACK: number; readonly MAX_TERMS: number; readonly TOKEN_AHEAD: number; readonly TOKEN_LIFE: number; readonly JOB_LEN: number; readonly BALANCE_LEN: number;
  readonly BIND_LEN: number; readonly REP_LEN: number; readonly KEY_DELAY: number; readonly KEY_TTL: number; readonly K_HDR: number; readonly KEY_TAIL: number;
  readonly OTHER: number; readonly PRIVATE: number; readonly PRIVATE_FLAG: number; readonly MAX_ISS: number; readonly T_IHASH: number;
  readonly ERRORS: Record<number, string>;
  /** [name, account names, tag] of each knos-pay instruction, in the order of the tags (0..27), under the names of idl/knos_pay_v2.json. */
  readonly PAY_IXS: readonly (readonly [string, readonly string[], number])[];
  readonly BALX_LEN: number; readonly PLAN_LEN: number; readonly ORDER_LEN: number; readonly OPTS_LEN: number;
  /** Prices, in millionths of one whole unit of the mint (`units` gives the smallest units). */
  readonly ORDER_FEE_MIN: number; readonly ORDER_FEE_MAX: number; readonly ORDER_MIN_AMOUNT: number; readonly TIP: number; readonly TIP_FIRST: number; readonly PLAN_BPS_MIN: number;
  readonly MAX_HOLDBACK_BPS: number; readonly MAX_WARRANTY_DAYS: number; readonly MAX_KILL_BPS: number; readonly MAX_PAYEES: number;
  readonly F_FAUCET: 1; readonly F_PRIVATE: 2; readonly F_NEUTRAL: 4; readonly F_STANDING: 8; readonly F_TOKEN2022: 16;
  /** The mints the record counts real money in. */
  readonly COUNTED: readonly Address[];
  readonly HB_LEN: number; readonly DONE_LEN: number; readonly AS_LEN: number; readonly USED_LEN: number;
  /** Seconds: how long a cancelled order still takes a pay token, and how long after it was made a used marker can be closed. */
  readonly NOTICE: number; readonly USED_KEEP: number;

  /** `micro` millionths of one whole unit of a mint with `decimals` decimals, in the mint's smallest units. */
  units(micro: Num, decimals?: number): Num;
  /** The fee of a job (2.0), taken out of its amount. */
  feeOf(amount: Num, decimals?: number): Num;
  termsJson(terms: unknown): Bytes;
  termsHash(terms: Bytes | string): Promise<Bytes>;
  wfRepoHash(repository: string): Promise<Bytes>;
  funderKey(funder: Address | Num): Promise<Bytes>;
  fundAudience(issue: Num, amount: Num, mode: number, termsHex: string, balance: Address, workS?: number): string;
  namedBalance(audience: string): Address;
  payAudience(repoId: Num, issue: Num, payeeId: Num, headSha: string, termsHex: string, mode: number, address?: Address | null): string;
  bindAudience(address: Address): string;
  destination(bind: Bind | null, audience: string): Address | null;

  /** The fee of an order (2.1), which its funder pays on top of the amount. `bps`: FEE_BPS, or the owner's Plan. */
  orderFee(amount: Num, bps?: number, decimals?: number): Num;
  /** An order's scope. Public: sha256("knos3:scope" || repo id || issue). Private: sha256(salt || repo id || issue). */
  scopeOf(repoId: Num, issue: Num, salt?: Bytes | string | null): Promise<Bytes>;
  /** sha256 of a token's signature bytes: what names its single-use marker. */
  sigHash(token: string | Bytes): Promise<Bytes>;
  /** The 48 bytes a funder fixes beside the amount and the terms. */
  opts(o?: OrderOptions): Bytes;
  orderFundAudience(issue: Num, amount: Num, mode: number, termsHex: string, balance: Address, workS?: number, seq?: number, options?: Bytes | null): string;
  /** `payees`: 1..=4 of [GitHub id, basis points, address or null]; the basis points add up to 10000. */
  payeesText(payees: Payee[]): string;
  orderPayAudience(order: Address, headSha: string, termsHex: string, mode: number, pr: Num, payees: Payee[]): string;
  payeesOf(audience: string): Payee[];
  orderDestination(bind: Bind | null, address: Address | null): Address | null;
  /** The fee rate of an owner's orders now: its Plan's while it lasts, FEE_BPS otherwise. */
  planBps(plan: Plan | null, now: Num): number;

  readJob(raw: Bytes | null): Job | null;
  readBalance(raw: Bytes | null): Balance | null;
  readBind(raw: Bytes | null): Bind | null;
  readRep(raw: Bytes | null): Standing;
  readPause(raw: Bytes | null): Num;
  readRate(raw: Bytes | null): [Num, Num];
  readOrder(raw: Bytes | null): Order | null;
  readBalx(raw: Bytes | null): Balx | null;
  readPlan(raw: Bytes | null): Plan | null;
  readKey(raw: Bytes | null): Key | null;
  /** For a verified token account of an issuer that is not GitHub or GitLab: [sha256 of the issuer's URL (hex), the registrant of a private key or null]. */
  tokenIssuer(raw: Bytes | null): [string, Address | null] | null;
  /** The URL in an issuer account. */
  readIss(raw: Bytes | null): string | null;
  keyAccountHash(raw: Bytes): Promise<string>;
  keyUsable(key: Key | null, now: Num): [boolean, string];
  errorWords(err: unknown): string | null;
  /** What the fund audience of a PRIVATE order carries as its terms: sha256(scope || terms hash). */
  privateFundTerms(scope: Bytes | string, termsHash: Bytes | string): Promise<Bytes>;
  /** The arbiter's ruling: who is paid, in what shares. Relayed with payOrderIx. */
  ruleAudience(order: Address, payees: Payee[]): string;
  /** An organisation's bind token. */
  orgBindAudience(address: Address): string;
  takeAudience(order: Address, takerId: Num, days: number): string;
  cancelAudience(order: Address): string;
  revertAudience(order: Address, headSha: string): string;
  readHoldback(raw: Bytes | null): Holdback | null;
  /** The assignee; with `o`, null too when the assignment was made for an earlier order at the same address. */
  readAssign(raw: Bytes | null, o?: Order | null): Address | null;
  /** Where the program pays one payee of an order: its assignee, else the address the token carries, else its bound wallet. */
  payeeWallet(assign: Bytes | null, o: Order, bind: Bind | null, address: Address | null): Address | null;
  readMarker(raw: Bytes | null): Marker | null;
  /** What a refund owes the taker first, when an open order was cancelled while reserved. */
  killFee(o: Order): Num;
  /** The name of each of the `count` accounts of one knos-pay instruction, in order. */
  accountNames(name: string, count: number): string[];
  client(ids: ProgramIds): V2Client;
}
export const v2: V2;

// ---- knos-meter ---------------------------------------------------------------------------------------------------------------
export interface MeterCredits {
  tokenProgram: Address; decimals: number; ownerId: Num; authority: Address; mint: Address; spent: Num; evaluations: Num; wfRepoHash: string; wfSha: string;
}
export interface MeterPlan { tier: number; month: number; ownerId: Num; rate: Num; expiry: Num; used: Num }
/** `payer`: the relayer that paid its rent and the only one that closes it; `closeAfter`: the chain time from which it can. Both null for a mark from before CloseMark. */
export interface MeterMark { accepted: boolean; month: number; buyerId: Num; sellerId: Num; time: Num; rate: Num; fee: Num; payer: Address | null; closeAfter: Num | null }
/** One buyer, one seller, one month. */
export interface MeterMonth { buyerId: Num; sellerId: Num; month: number; evaluations: number; accepted: number; rejected: number; value: Num; fees: Num }
export interface Evaluation { buyerId: Num; sellerId: Num; order: string; artifact: string; policy: string; milestone: number; accepted: boolean; rate: Num }
/** What meter.statement reads: the transactions that named an address (newest first) and the log of each. */
export interface MeterLedger {
  history(address: Address, most?: number): Iterable<string> | AsyncIterable<string> | Promise<Iterable<string> | AsyncIterable<string>>;
  logs(signature: string): string[] | Promise<string[]>;
}
export interface MeterClient {
  program: Address;
  auth(): Promise<Address>;
  creditsPda(ownerId: Num, authority: Address, mint: Address): Promise<Address>;
  crtokPda(credits: Address): Promise<Address>;
  planPda(ownerId: Num): Promise<Address>;
  markPda(buyerId: Num, evalKey: Bytes | string): Promise<Address>;
  monthPda(buyerId: Num, sellerId: Num, month: number): Promise<Address>;
  openCreditsIx(a: { authority: Address; ownerId: Num; mint: Address; wfRepo: string; wfSha: string; tokenProgram?: Address }): Promise<Instruction>;
  depositIx(a: { source: Address; owner: Address; credits: Address; mint: Address; amount: Num; decimals: number; tokenProgram?: Address }): Promise<Instruction>;
  withdrawCreditsIx(a: { authority: Address; credits: Address; mint: Address; amount?: Num; destToken?: Address | null; tokenProgram?: Address }): Promise<Instruction>;
  setPlanIx(a: { feeOwner: Address; payer: Address; ownerId: Num; tier: number; rate: Num; expiry: Num }): Promise<Instruction>;
  recordIx(a: { relayer: Address; token: Address; key: Address; credits: Address; c: MeterCredits; audience: string; now: Num; feeToken?: Address | null }): Promise<Instruction>;
  /** The relayer that paid a mark's rent takes it back and the mark is gone; refused before the mark's closeAfter. */
  closeMarkIx(a: { payer: Address; mark: Address }): Instruction;
  /** Every mark whose rent `payer` put up: [address, mark], from one getProgramAccounts of the RPC endpoint `url`. */
  marksOf(url: string, payer: Address): Promise<[Address, MeterMark][]>;
}
export interface Meter {
  readonly MICRO: number; readonly FEE: number; readonly PLAN_MIN: number; readonly FREE_PER_MONTH: number; readonly MIN_DECIMALS: number; readonly MAX_DECIMALS: number;
  readonly EXTENSIONS: readonly number[]; readonly CREDITS_LEN: number; readonly PLAN_LEN: number; readonly MARK_LEN: number; readonly MONTH_LEN: number;
  /** A mark written before CloseMark existed is this long; where a mark keeps its payer; seconds past a month's end a token issued in it can still be accepted. */
  readonly MARK_LEN_1: number; readonly MARK_PAYER: number; readonly MARK_GRACE: number; readonly CLOSED: string;
  readonly WORKFLOWS: readonly string[]; readonly EVAL: string; readonly ERRORS: Record<number, string>;
  /** A rate (millionths of a whole unit) in the smallest units of a mint with these decimals, rounded down. */
  feeUnits(rate: Num, decimals: number): Num;
  /** The UTC calendar month of a unix time, as the program computes it: 202610. */
  yyyymm(time: Num): number;
  /** The first second of the UTC calendar month after the one `time` is in. */
  nextMonth(time: Num): number;
  /** From when a mark recorded at `time` can be closed. */
  closeAfter(time: Num): number;
  /** The addresses of the marks (of marksOf) that CloseMark takes at `now`. */
  closable(marks: [Address, MeterMark][], now: Num): Address[];
  evalAudience(buyerId: Num, sellerId: Num, order: Bytes | string, artifact: string, policy: Bytes | string, milestone: number, verdict: number | boolean, rate: Num): string;
  parseAudience(audience: string): Evaluation;
  evalKey(order: Bytes | string, artifact: string, policy: Bytes | string, milestone: number): Promise<Bytes>;
  readCredits(raw: Bytes | null): MeterCredits | null;
  /** An owner with no account has no plan and has used nothing. */
  readPlan(raw: Bytes | null): MeterPlan;
  rateAt(plan: MeterPlan, now: Num): Num;
  usedIn(plan: MeterPlan, month: number): Num;
  readMark(raw: Bytes | null): MeterMark | null;
  readMonth(raw: Bytes | null, buyerId?: Num, sellerId?: Num, month?: number): MeterMonth;
  /** What the next billable evaluation of this owner costs at `now`, in the mint's smallest units. */
  quote(plan: MeterPlan, decimals: number, now: Num): Num;
  parseEval(line: string): Record<string, string> | null;
  /** The month of one buyer and one seller, recomputed from the meter's own log lines. */
  statement(ledger: MeterLedger, buyerId: Num, sellerId: Num, month: number, program: Address, most?: number): Promise<MeterMonth>;
  client(program: Address): MeterClient;
}
export const meter: Meter;

/** The lines programs logged in one transaction, without "Program log: "; with `program`, only what that program itself logged. */
export function said(logs: string[], program?: Address | null): string[];

// ---- transactions ----------------------------------------------------------------------------------------------------------------
/** The legacy message: the header, every account once (the fee payer first), the blockhash, the instructions by index. */
export function serializeMessage(ixs: Instruction[], payer: Address, recentBlockhash: Address): Bytes;
/** The unsigned legacy transaction: one empty signature for each signer, then the message. At most 1232 bytes fit. */
export function serializeTx(ixs: Instruction[], payer: Address, recentBlockhash: Address): Bytes;
export function messageOf(tx: Bytes): Bytes;
/** The compute budget of a v1 message. `computeUnitLimit` is required (an unset limit is zero units); `priorityFee` is in micro-lamports. */
export interface V1Config { computeUnitLimit: number; priorityFee?: Num; loadedAccountsDataSizeLimit?: number; heapSize?: number }
/** The v1 message (SIMD-0385): 0x81, the header, the settings, the blockhash, the accounts, the instructions. */
export function serializeMessageV1(ixs: Instruction[], payer: Address, recentBlockhash: Address, config: V1Config): Bytes;
/** The unsigned v1 transaction: the message, then one empty signature for each signer. At most 4,096 bytes fit. */
export function serializeTxV1(ixs: Instruction[], payer: Address, recentBlockhash: Address, config: V1Config): Bytes;
export function messageOfV1(tx: Bytes): Bytes;

// ---- wallets ------------------------------------------------------------------------------------------------------------------------
export interface Wallet {
  name: string; kind: "standard" | "phantom" | "solflare"; icon?: string;
  /** Asks the wallet for an account; resolves to its address. */
  connect(chain?: string): Promise<Address>;
  /** The wallet shows the transaction, signs and sends it; resolves to its signature (base58). */
  signAndSend(tx: Bytes, chain?: string): Promise<string>;
}
/** The wallets this page can ask: Wallet Standard first, then Phantom's and Solflare's own providers. */
export function wallets(win?: unknown): Wallet[];

// ---- JSON-RPC ----------------------------------------------------------------------------------------------------------------------------
export function rpc(url: string, method: string, params: unknown[]): Promise<any>;
export function account(url: string, address: Address): Promise<Bytes | null>;
export interface AccountInfo { owner: Address; data: Bytes; lamports: number }
export function accountInfo(url: string, address: Address): Promise<AccountInfo | null>;
export function accounts(url: string, addresses: Address[]): Promise<(AccountInfo | null)[]>;
/** The chain's clock: the time of the latest confirmed block, never the local clock. */
export function chainTime(url: string): Promise<number>;
export function programAccounts(url: string, program: Address, size: number, offset?: number | null, bytes?: Bytes | null): Promise<{ address: Address; data: Bytes }[]>;
export function confirmed(url: string, signature: string, seconds?: number, pause?: (ms: number) => Promise<unknown>): Promise<{ ok: boolean; err: unknown } | null>;
