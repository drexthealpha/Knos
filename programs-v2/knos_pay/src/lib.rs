//! knos-pay, the second deployment: pay on proof. A funder puts a bounty for one issue of one GitHub repository in
//! escrow. It is paid to the author of the pull request that meets the terms fixed at funding, when GitHub itself
//! signs a token saying the funder's pinned prove.yml workflow saw every funded condition met at the merged commit.
//! The token is verified on chain by knos-oidc (OIDC_ID). This program is upgradeable only through a multisig with a
//! public 48-hour delay, until an outside review; then made immutable. In the code below no key of Knos's moves money
//! or chooses where it goes: the guardian (another multisig) can refuse NEW funding for at most seven days per
//! signature (Pause), and nothing else here. In knos-oidc its guardian can revoke a signing key; this program then
//! refuses every token that key verified (TOKENS). A proof signed with it pays nothing: the job waits for a proof
//! under a key that is good, or goes back to its funder at the deadline (Refund needs no token). A revocation can
//! only make this program refuse: nothing makes it accept a token GitHub did not sign.
//!
//! WHERE MONEY CAN GO. Tokens leave an account of this program only by these six transfers, each a TransferChecked
//! (the mint is named, its decimals checked) between accounts of one mint:
//!   a Balance's token account -> the mint's vault         FundBalance, on a fund token: the job is credited
//!   a wallet's token account  -> the mint's vault         FundWallet, the wallet signs: the job is credited
//!   a Balance's token account -> a token account of the wallet that opened that Balance       Withdraw, that wallet signs
//!   the vault -> a token account of FEE_OWNER             Pay, Settle: the fee, fee_of(amount)
//!   the vault -> a token account of the payee's wallet    Pay, Settle: the rest of the job's amount
//!   the vault -> where the job's money came from          Refund: that Balance's token account, or a token account of the funding wallet
//! A job is credited with what its vault received (the vault's balance after the transfer minus before). A payment
//! and a refund move exactly the job's amount and close the job in the same instruction. So in every mint the open
//! and held jobs add up to exactly what these instructions have left in the vault. Tokens someone sends to a vault
//! directly belong to no job and no instruction moves them; tokens a mint's issuer takes out of a vault (a permanent
//! delegate can) leave the jobs as they were, unpaid until the tokens are back. The devnet faucet mints test USDC,
//! into a faucet Balance only. Lamports: a job's rent goes back to whoever paid it (`rent_to`) when the job closes;
//! the other accounts keep theirs.
//!
//! 2.1: WORK ORDERS. Instructions 0..11 are 2.0 and keep their bytes, but for four fixes: bounds and the fee floor are
//! whole units of the mint (10^decimals, read from the mint); the record counts real money only in Circle's USDC;
//! Token-2022 mints pass an allow-list of extensions; a Balance can carry a side account of limits (FundBalance takes
//! it as a 14th account once it exists); and every instruction that takes a token takes that token's single-use
//! marker, `used` (ONE MARKER, below). Everything else of 2.1 is new instruction numbers and one new kind of account, the Order (order.rs: its
//! funding; order_pay.rs: its payment and refund; order_judge.rs: who may sign for it; order_terms.rs: what it can
//! promise), whose audiences start `knos3:`. An order's money is in a token account of its own, ["ov", order]:
//!   a wallet's token account  -> the order's account      FundOrderWallet, TopUp: the wallet signs
//!   a Balance's token account -> the order's account      FundOrderBalance (a fund token), TopUp (the Balance's wallet signs)
//!   the order's account -> a token account of each payee's wallet     PayOrder, SettleOrder: the payee's share of what is paid now;
//!                                                                     Release: its part of the holdback, to the wallet recorded at payment
//!   the order's account -> a token account of the relayer             PayOrder, SettleOrder, Release: the tip, out of the fee
//!   the order's account -> a token account of FEE_OWNER               PayOrder, SettleOrder, Release: the rest of the fee
//!   the order's account -> a token account of the taker's wallet      RefundOrder: the kill fee of an order cancelled while reserved
//!   the order's account -> where the order's money came from          RefundOrder, Revert: everything it holds
//! A payee's wallet is the one it assigned this order's payment to (Assign), else the address its token carries, else
//! its Bind. The funder pays the fee on top of the amount (order_fee); it waits in the order's account with the
//! amount. An order is credited with exactly what its account received, and its account is closed with it.
//!
//! ACCOUNTS. All are PDAs of this program, created by it; layouts are in state.rs; ids in seeds are u64 little-endian.
//!   auth     ["auth"]                            owns every token account below and is the faucet mint's authority; holds nothing
//!   vault    ["vault", mint]                     token account: the money of every open and held job in that mint
//!   Balance  ["bal", owner id, authority, mint]  money a wallet (authority) set aside for bounties in the repositories of one
//!                                                GitHub owner (a user or an organisation), who may spend it, how much per job
//!   baltok   ["baltok", balance]                 the Balance's token account. Anyone adds money with a plain transfer to it.
//!   Job      ["job", repo id, issue, source]     one bounty; source is the Balance it was funded from, or the funding wallet
//!   Bind     ["bind", user id]                   the wallet a GitHub user is paid at
//!   Rep      ["rep", user id]                    a GitHub user's public record of payments
//!   Pair     ["pair", payee id, funder key]      exists once this funder has paid this payee in real money
//!   Pause    ["pause"]                           new funding is refused until this time
//!   BalX     ["balx", balance]                   a Balance's side account: limits per day and in total, repositories, workflows commit
//!   Plan     ["plan", owner id]                  a lower fee rate for one repository owner's orders until an expiry
//!   Used     ["used", sha256(token signature)]   exists once an instruction took that token: no instruction takes it again
//!   Order    ["ord", scope, source, seq u32]     one work order; scope is sha256("knos3:scope" || repo id || issue), or a private one
//!   ov       ["ov", order]                       token account: that order's money and nothing else
//!   Hb       ["hb", order]                       where the holdback of an order in WARRANTY goes: the wallets paid, and their parts
//!   Done     ["done", order, pr u64]             this standing order has paid this pull request
//!   As       ["as", order, payee id]             the wallet this order pays for that payee instead of the payee's own
//!   Rate     ["rate", repo id]                   devnet: the faucet's last use by this repository
//!   mint     ["mint"]                            devnet: the faucet's test-USDC mint (SPL Token, 6 decimals)
//!
//! TOKENS. A token is a GitHub Actions OIDC token in an account that knos-oidc owns and marked VERIFIED (GitHub's RS256
//! signature was checked on chain). Every instruction that takes one requires, in gh.rs: issuer GitHub; at most
//! knos_oidc::LATE (an hour) past its expiry; `iat` at most TOKEN_AHEAD ahead of the chain's clock and `exp` at most
//! TOKEN_LIFE after `iat` (GitHub's tokens live five minutes; nothing works for ever); `runner_environment`
//! github-hosted. And the key that verified the token must still be good: the instruction takes knos-oidc's key
//! account (`key`) right after the token account, and it must be the account the token account names (its bytes
//! 18..50), owned by knos-oidc, and usable at the chain's time by knos_oidc::key_usable. So a token is refused from
//! the moment its key is revoked or expires, with knos-oidc's own code (76 not active, 77 expired, 78 revoked); once
//! an expired key is attested again (knos-oidc's Refresh) its tokens work for what is left of their own time. A token
//! is not a secret: anyone may relay one, and what it can do is fixed by its claims and its audience (`aud`):
//!   fund  knos2:fund:<issue>:<amount units>:<mode 0|1>:<terms hash hex>:<work seconds>:<balance address>         from fund.yml
//!   pay   knos2:pay:<repository id>:<issue>:<payee github id>:<head sha>:<terms hash hex>:<mode>:<address or ->  from prove.yml
//!   bind  knos2:bind:<address>                                                                                   from the pinned claim.yml
//!   fund  knos3:fund:<issue>:<amount units>:<mode>:<terms hash hex>:<work seconds>:<balance address>:<seq>:<opts hex>   an order, from fund.yml
//!   pay   knos3:pay:<order address>:<head sha>:<terms hash hex>:<mode>:<pr>:<payees>                               an order, from a judge
//!         payees: 1..=4 of <github id>.<basis points>.<address or -> joined by `,`; the basis points add up to 10000
//!   auto  knos3:auto:<order address>:<head sha>:<terms hash hex>:1:<pr>:<payee>   an AUTO order, unmerged, from its own prove.yml (order_judge.rs, e)
//!   rule  knos3:rule:<order address>:<payees>                         an order's arbiter rules, from attest.yml started by hand
//!   revert knos3:revert:<order address>:<head sha>                    an order's holdback goes back, from a judge (a, b or c)
//!   take  knos3:take:<order address>:<taker github id>:<days>         an order is reserved, from its COMMAND job (fund.yml) or prove.yml,
//!                                                                     or attest.yml by hand (a NEUTRAL order): the taker's own run
//!   cancel knos3:cancel:<order address>                               a Balance's order gets notice, from its COMMAND job or prove.yml
//!   bind  knos3:bind:<address>                                        an organisation's wallet, from the pinned claim.yml
//! ONE MARKER. A token is accepted once. Every instruction that takes one (3 FundBalance, 5 Pay, 8 Bind, 11 FaucetOpen,
//! 16 FundOrderBalance, 17 PayOrder, 19 Revert, 20 Reserve, 21 Cancel on a Balance's order, 25 BindOrg) makes the
//! token's marker ["used", sha256(the token's signature bytes)] once it has decided to accept the token and before it
//! changes anything else, and refuses the token (E_REPLAY) when the marker is there. So the same token is never
//! accepted twice, by the same instruction or by another, whatever the accounts it names hold by then: an order that
//! was paid and funded again at the same address is not paid again by the token that paid it. The one pair that is
//! designed: on devnet FaucetOpen marks its fund token MINTED, and the funding instruction that follows takes exactly
//! such a token and marks it used. The marker keeps who paid its rent and the time after which no instruction could
//! accept the token anyway; CloseMarker gives the rent back after that. The relayer (Cancel: the signer) pays the
//! rent and must be writable. An order's `not_before` is the chain's time at its funding less CLOCK_SLACK, never a
//! token's `iat`: no token issued before an order was funded acts on it.
//! A fund token names the Balance it spends, by its address as Solana prints it: the funder's own workflow chooses
//! the Balance when it asks GitHub for the token (it reads the chain), and a relayer cannot spend another one with it.
//! A job pins its workflows at funding: the repository that holds them (sha256 of "owner/name", from the fund token's
//! `job_workflow_ref`) and their commit (`job_workflow_sha`). Only that repository's prove.yml at that commit proves
//! the job. The terms (what must hold for the bounty to be paid) are a JSON document: the funding instruction carries
//! it, stores its sha256 in the job and logs it, so the terms are public and cannot change, and a pay token must carry
//! the same hash. mode 0 (merge) and 1 (tests) are the two ways prove.yml judges; this program only matches them.
//!
//! INSTRUCTIONS. The first byte of the data is the tag; integers are little-endian; (s) signs, (w) is writable.
//!   0 OpenBalance  authority(s,w) balance(w) baltok(w) mint auth token_program system
//!                  data: owner_id u64, cap u64, spenders [u64; 4]
//!                  Any wallet, for any GitHub owner id but 0: it is the wallet's own money. Creates the Balance and its
//!                  token account, both empty. The mint must pass the mint rules. No money moves.
//!   1 SetBalance   authority(s) balance(w)
//!                  data: cap u64, spenders [u64; 4]
//!                  The wallet that opened the Balance sets its cap per job (0: none) and its spenders (0: empty).
//!   2 Withdraw     authority(s) balance baltok(w) dest_token(w) mint auth token_program
//!                  data: amount u64
//!                  The wallet that opened the Balance takes unspent money back (amount 0: all of it). dest_token must be
//!                  a token account of the Balance's mint owned by that same wallet. A faucet Balance cannot withdraw.
//!                  Never paused.
//!   3 FundBalance  relayer(s,w) fund_token key balance(w) baltok(w) job(w) vault(w) mint auth token_program system pause used(w) balx(w)
//!                  data: terms bytes
//!                  Anyone relays. Not paused. The token: workflow file fund.yml; event `issue_comment` or `issues`, and
//!                  `run_attempt` 1 (a re-run keeps the first actor's name whoever starts it); the audience names this
//!                  Balance; `repository_owner_id` is the Balance's owner; `actor_id` is that owner or one of the
//!                  Balance's spenders (a faucet Balance: any actor); `iat` is later than the Balance's last, which is
//!                  then set to it: a fund token works once, and a Balance takes its tokens in the order GitHub issued
//!                  them (of two issued in the same second, one). The audience:
//!                  amount MIN_AMOUNT..=MAX_AMOUNT and at most the Balance's cap, work MIN_WORK..=MAX_WORK seconds, and
//!                  the hash of the terms in the data (at most MAX_TERMS bytes, printable ASCII). The Balance's token
//!                  account holds the amount; the job ["job", repository_id, issue, balance] does not exist; the mint
//!                  passes the mint rules. Money: the amount, baltok -> vault. The job refunds to baltok, its rent is the
//!                  relayer's, its workflows are the token's, its deadline is now + work, proofs count from the token's `iat`.
//!                  2.1: `used` is the token's marker; `balx` is passed (and then required) only once the Balance has a
//!                  side account (SetBalanceX).
//!   4 FundWallet   funder(s,w) job(w) funder_token(w) vault(w) mint auth token_program system pause
//!                  data: repo_id u64, issue u64, amount u64, work i64, mode u8, wf_repo [u8; 32], wf_sha [u8; 40], terms bytes
//!                  The funding wallet signs. Not paused. The same bounds; repo_id not 0; wf_sha 40 hex characters; the job
//!                  ["job", repo_id, issue, funder] does not exist; the mint passes the mint rules. Money: the amount,
//!                  funder_token -> vault (the token program checks the wallet's authority over funder_token). The job
//!                  refunds to the wallet, its rent is the wallet's, proofs count from now less CLOCK_SLACK.
//!   5 Pay          relayer(s,w) pay_token key job(w) bind dest_token(w) rep(w) pair(w) vault(w) fee_token(w) auth rent_to(w) mint token_program system used(w)
//!                  Anyone relays. The job is OPEN and its deadline has not passed. The token: workflow file prove.yml of
//!                  the job's pinned repository at the job's pinned commit; `repository_id` is the job's; `iat` not
//!                  before the job's `not_before`. The audience: the job's repository, issue, terms hash and mode; a payee
//!                  id that is not 0; a head sha of 40 hex characters; an address or "-". Destination: the wallet in the
//!                  payee's Bind (the account must be ["bind", payee], so a Bind cannot be hidden); with no Bind, the
//!                  address in the audience; with neither, no money moves and the job becomes HELD for that payee until
//!                  now + HOLD (the accounts after `bind` are then not used). A proof may be run again: any run of that
//!                  workflow counts, a re-run included. Paying is described under Settle. 2.1: a pay token pays, or
//!                  holds, exactly one job: `used` is ["used", sha256(the token's signature bytes)], created here, and
//!                  a second job is refused with it (E_REPLAY).
//!   6 Settle       relayer(s,w) job(w) bind dest_token(w) rep(w) pair(w) vault(w) fee_token(w) auth rent_to(w) mint token_program system
//!                  Anyone relays. A HELD job, not past its hold, whose payee now has a Bind: paid to that wallet.
//!                  Paying (Pay with a destination, and Settle): dest_token is a token account of the job's mint owned by
//!                  the destination wallet, which cannot be ["auth"]; fee_token is one owned by FEE_OWNER; mint and
//!                  token_program are the job's; vault is the mint's; rent_to is the job's. Money: fee_of(amount) from the
//!                  vault to fee_token, the rest to dest_token. Then the record (Rep, Pair) is updated and the job is
//!                  closed. After a proof there is no veto and no waiting time: the payment is final.
//!   7 Refund       relayer(s,w) job(w) vault(w) refund_token(w) auth rent_to(w) mint token_program
//!                  Anyone relays, and no token is needed: it works whatever happens to GitHub or to Knos. The job is OPEN
//!                  past its deadline, or HELD past its hold. Money: the job's amount from the vault to refund_token,
//!                  which is exactly the Balance's token account (a Balance's job) or a token account of the job's mint
//!                  owned by the funding wallet (a wallet's job). The job is closed.
//!   8 Bind         relayer(s,w) bind_token key bind(w) system used(w)
//!                  Anyone relays. The token: `job_workflow_ref` starts with CLAIM_REF and `job_workflow_sha` is CLAIM_SHA
//!                  (the pinned claim workflow); `actor_id` equals `repository_owner_id` and is not 0; `repository` ends
//!                  with "/knos-claim"; event `workflow_dispatch` only (a run its owner started by hand: a push, even
//!                  the first, is refused, because a prefilled new-repository link can choose what a first push
//!                  says); `run_attempt` 1; the audience's address is a key. Sets ["bind", actor_id] to that address.
//!                  A Bind that exists is replaced only by a token with a later `iat`. No money moves.
//!   9 Pause        guardian(s) payer(s,w) pause(w) system
//!                  data: seconds u32
//!                  GUARDIAN signs. FundBalance and FundWallet are refused until now + seconds (at most PAUSE_MAX; 0 lifts
//!                  it). A pause ends by itself; keeping one needs the guardian's signature again. Every other instruction
//!                  ignores it: payments, refunds, withdrawals and binds cannot be paused.
//!   10 InitFaucet  payer(s,w) mint(w) auth token_program system
//!                  Devnet builds only. Anyone, once. Creates the faucet's test-USDC mint; its mint authority is ["auth"].
//!   11 FaucetOpen  relayer(s,w) fund_token key balance(w) baltok(w) mint(w) auth token_program system rate(w) used(w)
//!                  Devnet builds only. Anyone relays. The same fund token as FundBalance (fund.yml, event, first attempt,
//!                  bounds), amount at most FAUCET_CAP, once per repository per FUND_PERIOD and only with a later `iat`
//!                  than the last (Rate). The Balance its audience names must be the faucet Balance ["bal",
//!                  repository_owner_id, ["auth"], faucet mint]: a token that names a Balance of real money mints
//!                  nothing. Mints the amount of test USDC into that Balance (created on first use and flagged: any
//!                  actor spends it, nobody withdraws it). The token's marker is made here as MINTED: the funding
//!                  instruction that spends that Balance with it is the one thing that still takes it.
//!   12 Version
//!                  Logs `knos2:version 1`. A client simulates it to learn whether 2.1 is live (2.0 refuses the tag).
//!   13 SetBalanceX authority(s,w) balance(w) balx(w) system
//!                  data: day_limit u64, total_limit u64, repos [u64; 8], wf_sha [u8; 40]
//!                  The wallet that opened the Balance sets its side account ["balx", balance] (created on first use;
//!                  its counters stay). Limits are in the mint's smallest units (0: none); repos: the only repository
//!                  ids that may spend it (all zero: any repository of the owner); wf_sha: the only commit of the
//!                  pinned workflows that may spend it (all zero: any). Every funding from the Balance then enforces it.
//!   14 SetPlan     fee_owner(s) payer(s,w) plan(w) system
//!                  data: owner_id u64, fee_bps u16, expires i64
//!                  FEE_OWNER sets the fee rate of the orders funded from Balances of one repository owner:
//!                  PLAN_BPS_MIN..=FEE_BPS basis points while now < expires (which must be in the future).
//!   15 FundOrderWallet funder(s,w) order(w) ov(w) funder_token(w) mint auth token_program system pause
//!                  data: issue u64, repo_id u64, amount u64, mode u8, work i64, seq u32, opts [u8; 48], wf_repo [u8; 32], wf_sha [u8; 40], terms bytes
//!                  Any wallet funds an order for an issue of any public repository; nothing is needed in that
//!                  repository. Not paused. Amount ORDER_MIN_AMOUNT..=MAX_AMOUNT whole units; the same work and mode
//!                  bounds as a job; repo_id not 0; the order ["ord", scope, funder, seq] does not exist; the mint
//!                  passes the mint rules. opts (order.rs): flags u8 (PRIVATE 2, NEUTRAL 4, STANDING 8),
//!                  holdback_bps u16, warranty_days u16, kill_bps u16, reserve_days u8, rate u64, arbiter_id u64,
//!                  judge_repo_id u64, salted u8, 15 zero bytes. A PRIVATE order (salted 1): repo_id and issue are 0
//!                  and `terms` is its scope [32] then the hash of its terms [32]. Money: amount + order_fee(amount),
//!                  funder_token -> ov. Logs knos3:funded and knos3:terms.
//!   16 FundOrderBalance relayer(s,w) fund_token key balance(w) baltok(w) balx(w) plan order(w) ov(w) used(w) mint auth token_program system pause
//!                  data: terms bytes
//!                  Anyone relays. Not paused. The token as FundBalance's (fund.yml, a comment or an issue event, first
//!                  attempt, the Balance's owner, the owner or a spender as actor), with the knos3 audience, which
//!                  names this Balance, the seq and the options. It works once: its marker `used` is made here. The
//!                  amount is at most the Balance's cap; amount + fee (at the owner's Plan rate, `plan` being
//!                  ["plan", owner id]) is within the side account's limits and what the Balance holds. Money: amount
//!                  + fee, baltok -> ov. The order refunds to baltok; its rent is the relayer's.
//!   17 PayOrder    relayer(s,w) pay_token key order(w) ov(w) tip_token(w) fee_token(w) auth rent_to(w) mint token_program system ata_program used(w) bind wallet dest_token(w) rep(w) pair(w)
//!                  The last five are the first payee's; five more follow for each further payee of the audience, in its
//!                  order; then one ["as", order, payee] per payee, in the same order (it need not exist, but cannot be
//!                  left out); then ["done", order, pr](w) for a STANDING order, or ["hb", order](w) for one with a holdback.
//!                  `used` is the token's marker: a pay token or a ruling pays, or holds, once.
//!                  Anyone relays. The order is OPEN before its deadline. The token is a judge's (order_judge.rs): the
//!                  workflows of the order's pinned repository at its pinned commit, a first attempt, and one of
//!                  a. prove.yml run in the order's own repository; b. for a NEUTRAL order that is not PRIVATE,
//!                  attest.yml started by hand by the account that owns the repository it ran in; c. prove.yml or
//!                  attest.yml run in the order's judge repository; d. the ruling of the arbiter the order named
//!                  (audience knos3:rule:<order>:<payees>, attest.yml started by hand by him in a repository of his).
//!                  A PRIVATE order of a Balance also takes a pay token under a private key that the wallet which
//!                  opened that Balance registered. `iat` not before the order's `not_before`; the audience names
//!                  this order, its terms hash and mode. Each payee is paid at the wallet it assigned this order's
//!                  payment to (Assign), else at the address the token carries for it, else at the wallet in its
//!                  Bind; one payee with none: the order becomes HELD for it; several payees and one with none:
//!                  refused. `wallet` is that wallet; dest_token a token account of it (created here as its
//!                  associated token account when it does not exist). Money: each payee's share of what is paid now;
//!                  of the fee, TIP (TIP_FIRST when a payee's token account was created here) to tip_token, a token
//!                  account of the relayer, and the rest to fee_token, FEE_OWNER's. The record of each payee is
//!                  updated. What is paid now is all that is left of the amount, and the order and its token account
//!                  are then closed, rents to rent_to; except: a STANDING order pays its rate, once per pull request
//!                  (its marker `done` is made here), and stays OPEN while a rate is left; an order with a holdback
//!                  keeps that share (recorded in `hb`, made here) and is in WARRANTY until now + its warranty. On
//!                  those two every payee needs a wallet now (never HELD); an order that is both is refused (E_LATER).
//!   18 Release     relayer(s,w) order(w) ov(w) hb(w) tip_token(w) fee_token(w) auth rent_to(w) hb_payer(w) mint token_program
//!                  system ata_program, then for each recorded payee, in the record's order: wallet dest_token(w)
//!                  Anyone relays; no token. An order in WARRANTY, after its warranty: each wallet ["hb", order]
//!                  recorded receives its part of the holdback (its associated token account is created here when it
//!                  does not exist), the relayer the tip, FEE_OWNER what is left; the order, its token account and the
//!                  record are closed.
//!   19 Revert      relayer(s,w) revert_token key order(w) ov(w) hb(w) refund_token(w) auth rent_to(w) hb_payer(w) mint token_program system used(w)
//!                  Anyone relays. An order in WARRANTY, inside its warranty. The token: audience
//!                  knos3:revert:<order>:<head sha>, from judge a, b or c of the order (as PayOrder's; never the
//!                  arbiter), issued after the payment. Everything the order's account holds (the holdback and the fee
//!                  on it) goes to refund_token, where the order's money came from; all three accounts are closed.
//!                  It cannot touch what was already paid.
//!   20 Reserve     relayer(s,w) take_token key order(w) system used(w)
//!                  Anyone relays. The token: audience knos3:take:<order>:<taker id>:<days>, days 1..=the order's
//!                  reserve_days; from the order's pinned workflows at its pinned commit, a first attempt: fund.yml
//!                  (the COMMAND job, answering a comment) or prove.yml run in the order's own repository, or, for a
//!                  NEUTRAL order that is not PRIVATE, attest.yml started by hand by the account that owns the
//!                  repository it ran in. `actor_id` is the taker the audience names: a person reserves for himself.
//!                  The order (OPEN, not cancelled, not reserved now) is reserved for the taker until now + days.
//!   21 Cancel      signer(s,w) order(w) [cancel_token key system used(w)]
//!                  Once, on an OPEN order before its deadline: the deadline becomes min(deadline, now + NOTICE, seven
//!                  days); a pay token still pays until then. A wallet's order: the funding wallet signs. A Balance's
//!                  order: anyone signs, and the token has audience knos3:cancel:<order>, is from fund.yml or prove.yml
//!                  of the order's pinned workflows run in the order's own repository (a first attempt), and its
//!                  `actor_id` funded the order or owns the Balance. With a token the signer pays the rent of its marker
//!                  `used`, and only then must it be writable.
//!   22 RefundOrder relayer(s,w) order(w) ov(w) refund_token(w) auth rent_to(w) mint token_program
//!                  Anyone relays; no token. OPEN past its deadline or HELD past its hold: everything the order's
//!                  account holds goes to refund_token (the Balance's token account, or a token account of the
//!                  funding wallet); both accounts are closed. An order cancelled while reserved owes its taker
//!                  kill_bps of the amount first: two more accounts follow, the taker's Bind and a token account of
//!                  his bound wallet (w), and the kill fee goes there; when he has no wallet (or that account is not
//!                  his) the rest is refunded now and the order stays, HELD for him with the kill fee as its amount.
//!   23 TopUp       signer(s,w) order(w) ov(w) from_token(w) balance mint auth token_program pause
//!                  data: add u64
//!                  Not paused; the order is OPEN before its deadline; amount + add is within MAX_AMOUNT. A wallet's
//!                  order: the funding wallet signs. A Balance's order: `balance` is it, the wallet that opened it
//!                  signs, from_token is its token account. Money: add, and the fee on the new amount less the fee
//!                  already there (at the rate fixed at funding), from_token -> ov.
//!   24 Assign      signer(s,w) order bind as(w) system
//!                  data: payee u64, to [32]
//!                  The payee's bound wallet signs (once an assignment is set, only its current assignee): this
//!                  order's payment for that payee goes to the wallet `to`, recorded in ["as", order, payee]. What was
//!                  assigned cannot be taken back or assigned twice by the payee. No money moves.
//!   25 BindOrg     relayer(s,w) bind_token key bind(w) system used(w)
//!                  Anyone relays. An organisation's wallet (order_judge.rs). The token: audience knos3:bind:<address>;
//!                  the pinned claim workflow (CLAIM_REF at CLAIM_SHA or order_judge::CLAIM_SHA_ORG); `repository` ends
//!                  with "/knos-claim"; `workflow_dispatch`, `run_attempt` 1; `repository_owner_id` is not `actor_id`
//!                  (a member started it by hand in the organisation's repository). Sets ["bind", repository_owner_id];
//!                  never replaces a Bind that Bind wrote, and one of its own only with a later `iat`. No money moves.
//!   26 SettleOrder relayer(s,w) order(w) ov(w) tip_token(w) fee_token(w) auth rent_to(w) mint token_program system ata_program bind wallet dest_token(w) rep(w) pair(w)
//!                  Anyone relays. A HELD order, not past its hold, whose payee now has a Bind: paid as PayOrder pays
//!                  (to the wallet the payee assigned this order's payment to, if any: ["as", order, payee] follows).
//!   27 CloseMarker marker(w) rent_to(w) order
//!                  Anyone. A ["used", ...] marker once no token it stands for can be accepted any more (`order` is
//!                  not read), or a ["done", ...] marker once nothing of this program is at its order's address
//!                  (`order`): the marker is closed and its rent goes to rent_to, who paid it.
//! order_terms.rs gives the layouts of Hb, Done and As and the rules of 18 to 21, 24 and 27 in full.
//!
//! MINT RULES (token.rs). The mint's owner is SPL Token or Token-2022, and the token program passed is that owner.
//! Token accounts of a Token-2022 mint are created with the size GetAccountDataSize returns. When money enters
//! (OpenBalance, FundBalance, FundWallet, FaucetOpen, FundOrderWallet, FundOrderBalance) a Token-2022 mint's
//! extensions are walked, and the mint is refused unless every one is on token::ALLOWED: the extensions that change
//! nothing about who holds how much or whether a transfer goes through. A transfer hook (even one that names only an
//! authority), a transfer fee (even of zero), a permanent delegate, a default account state, Pausable,
//! NonTransferable and every extension this program does not know are refused. Money leaving escrow is never held to
//! these rules: what entered can go out. A mint's issuer keeps the powers its mint gives it over every holder
//! (freezing, by the freeze authority), and this program cannot take them away.
//!
//! THE RECORD. Rep counts a payment of a job or an order in the faucet's mint under test_paid/test_total; one in a
//! mint that is neither the faucet's nor Circle's USDC under test_paid, its amount nowhere; one whose funder is the
//! payee (the Balance's owner or the funding commenter is the payee, or a wallet's job is paid back to that wallet)
//! under self_paid; any other under paid/total (what reached the payee's wallet) and first/last, and under funders
//! when its Pair account is new. A funder is the funding wallet, or a Balance's GitHub owner (sha256("gh" || owner id)).
//!
//! LOGS, one line each, for an indexer (ids and amounts in decimal, addresses in base58, times in unix seconds):
//!   knos2:balance owner= authority= mint=          a Balance was opened
//!   knos2:funded repo= issue= amount= mode= by= source= faucet=      amount: what the vault received; by: the commenter's
//!                                                  GitHub id (0: a wallet); source: the Balance or the wallet
//!   knos2:terms <json>                             follows knos2:funded: the terms whose hash the job stores
//!   knos2:paid repo= issue= payee= amount= fee= to=                  amount: what reached the wallet `to`; fee: what FEE_OWNER got
//!   knos2:held repo= issue= payee= until=          knos2:refunded repo= issue= amount=
//!   knos2:bound user= wallet=                      knos2:withdrawn owner= authority= mint= amount=      knos2:paused until=
//!   knos2:version 1                                knos2:balancex balance= day= total=                  knos2:plan owner= bps= expires=
//!   knos3:funded order= repo= issue= seq= amount= fee= mode= by= source= flags= deadline=      then knos3:terms <json> (a public order)
//!   knos3:paid order= pr= payee= amount= to=       one per payee, then
//!   knos3:settled order= paid= of= fee= tip= judge=                  fee: what FEE_OWNER got; judge: 0 a, 1 b, 2 c, 3 d, 9 none (SettleOrder)
//!   knos3:held order= pr= payee= until=            knos3:refunded order= amount=            knos3:topup order= add= amount= fee=
//!   knos3:warranty order= held= until=             knos3:released order= payee= amount= to=             knos3:reverted order= amount= head=
//!   knos3:reserved order= taker= until=            knos3:cancelled order= at= deadline=                 knos3:kill order= taker= amount= held=
//!   knos3:assigned order= payee= to=               knos3:bound org= wallet= by=
pub mod fund;
pub mod gh;
pub mod gl;
pub mod order;
pub mod order_judge;
pub mod order_pay;
pub mod order_terms;
pub mod pay;
pub mod state;
pub mod token;

pub use knos_oidc::claims::err;
use solana_program::{account_info::AccountInfo, clock::Clock, entrypoint::ProgramResult, program_error::ProgramError, pubkey, pubkey::Pubkey, sysvar::Sysvar};

/// The knos-oidc program whose VERIFIED token accounts this program accepts (programs-v2/program_ids.json).
pub const OIDC_ID: Pubkey = pubkey!("FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W");
/// Fees go to a token account owned by this address (Knos's Squads vault). It has no other power.
pub const FEE_OWNER: Pubkey = pubkey!("4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo");
/// May pause new funding (Pause), and nothing else: a Squads vault.
pub const GUARDIAN: Pubkey = pubkey!("AT1aKj1DpgaWerxmS4YjDkNpWPNUtCCKVDvxLhFxg5Jc");
/// The claim workflow: a Bind token's `job_workflow_ref` must start with CLAIM_REF and its `job_workflow_sha` must be
/// CLAIM_SHA. A commit sha fixes the workflow file's content.
pub const CLAIM_REF: &[u8] = b"drexthealpha/knos-oidc-rotate/.github/workflows/claim.yml@";
pub const CLAIM_SHA: &[u8; 40] = b"80e796d341f65060767939c4e65a38ede5fa1ac8";

/// Test builds only (`--features testkeys`, which also makes knos-oidc trust the test keys): a test claim pin, and a
/// test guardian, the ed25519 key of the seed [7; 32]. Never deploy a testkeys build.
#[cfg(feature = "testkeys")]
pub const TEST_CLAIM_SHA: Option<&[u8; 40]> = Some(b"2222222222222222222222222222222222222222");
#[cfg(not(feature = "testkeys"))]
pub const TEST_CLAIM_SHA: Option<&[u8; 40]> = None;
#[cfg(feature = "testkeys")]
pub const TEST_GUARDIAN: Option<Pubkey> = Some(Pubkey::new_from_array([
    234, 74, 108, 99, 226, 156, 82, 10, 190, 245, 80, 123, 19, 46, 197, 249, 149, 71, 118, 174, 190, 190, 123, 146, 66, 30, 234, 105, 20, 70, 210, 44,
]));
#[cfg(not(feature = "testkeys"))]
pub const TEST_GUARDIAN: Option<Pubkey> = None;

/// Circle's USDC. The record (Rep) counts real money only in these mints (and, in a test build, TEST_USDC); the
/// faucet's mint is test money; a payment in any other mint is counted as a test payment and its amount not at all.
pub const USDC_DEVNET: Pubkey = pubkey!("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU");
pub const USDC_MAINNET: Pubkey = pubkey!("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v");
/// Test builds only: a mint the record counts as Circle's (the key of the seed [8; 32]: the tests create it), and a
/// key that may sign SetPlan beside FEE_OWNER (the seed [6; 32]). Fees never go to it.
#[cfg(feature = "testkeys")]
pub const TEST_USDC: Option<Pubkey> = Some(pubkey!("2KW2XRd9kwqet15Aha2oK3tYvd3nWbTFH1MBiRAv1BE1"));
#[cfg(not(feature = "testkeys"))]
pub const TEST_USDC: Option<Pubkey> = None;
#[cfg(feature = "testkeys")]
pub const TEST_PLAN_SIGNER: Option<Pubkey> = Some(pubkey!("AKkzLhjhyFtM9j7WAhbaqYpFe49cXeJBg2kzLRC2PnNa"));
#[cfg(not(feature = "testkeys"))]
pub const TEST_PLAN_SIGNER: Option<Pubkey> = None;

// Amounts below are millionths of ONE WHOLE UNIT of the mint (10^decimals of its smallest units): state::units turns
// them into the mint's smallest units with the decimals read from the mint. For a 6-decimal mint they are the same.
pub const FEE_BPS: u64 = 250;             // 2.5%: a job's fee, and the first tier of an order's
pub const FEE_MIN: u64 = 50_000;          // jobs (2.0): 0.05; never more than the amount
pub const MIN_AMOUNT: u64 = 1_000_000;    // jobs (2.0): 1.00
pub const MAX_AMOUNT: u64 = 100_000_000_000; // 100,000.00 per job and per order on devnet; a build for real money decides its own cap
// orders (2.1): the funder pays the fee on top of the amount; the payees receive the amount. The fee is marginal, in
// three tiers of the amount, and has a floor and no cap (order_fee).
pub const ORDER_FEE_MIN: u64 = 400_000;   // 0.40
pub const FEE_TIER_1: u64 = 1_000_000_000;   // the first 1,000.00: FEE_BPS, or the owner's Plan
pub const FEE_TIER_2: u64 = 50_000_000_000;  // from there to 50,000.00: FEE_BPS_2; above it: FEE_BPS_3
pub const FEE_BPS_2: u64 = 100;           // 1%
pub const FEE_BPS_3: u64 = 50;            // 0.5%
pub const ORDER_MIN_AMOUNT: u64 = 5_000_000; // 5.00
pub const TIP: u64 = 50_000;              // 0.05 of the fee goes to whoever paid for the paying transaction
pub const TIP_FIRST: u64 = 300_000;       // 0.30 when that transaction created a payee's token account
pub const PLAN_BPS_MIN: u64 = 50;         // a Plan lowers the fee rate to 50..=250 basis points
pub const MAX_HOLDBACK_BPS: u16 = 5000;
pub const MAX_WARRANTY_DAYS: u16 = 90;
pub const MAX_KILL_BPS: u16 = 2000;
pub const MAX_PAYEES: usize = 4;
pub const VERSION: u32 = 1;               // what Version logs: 2.1 is live (2.1 as first built, without ONE MARKER, was never deployed)
pub const MIN_WORK: i64 = 60;
pub const MAX_WORK: i64 = 90 * 86_400;
pub const HOLD: i64 = 180 * 86_400;       // how long a proven job waits for its payee to bind a wallet
pub const FAUCET_CAP: u64 = 100_000_000;  // devnet: at most 100 test USDC per faucet use
pub const FUND_PERIOD: i64 = 60;          // devnet: one faucet use per repository per minute
pub const CLOCK_SLACK: i64 = 30;          // the chain's clock and GitHub's can differ by this much
pub const TOKEN_AHEAD: i64 = 300;         // a token's `iat` may be this far ahead of the chain's clock (the clock can lag)
pub const TOKEN_LIFE: i64 = 3600;         // a token's `exp` is at most this long after its `iat` (GitHub's is 300 seconds)
pub const PAUSE_MAX: u32 = 7 * 86_400;
pub const MAX_TERMS: usize = 600;
pub const DEVNET: bool = cfg!(feature = "devnet");

// errors 60-63 are knos-oidc's claim reader's; 76-78 are knos-oidc's too: the key that verified a token is not active
// yet, has expired, or was revoked (gh.rs)
pub const E_ACCOUNTS: u32 = 80;  // a wrong account, or a missing signature
pub const E_TERMS: u32 = 81;     // amount, work time, mode, workflow commit, terms JSON or pause length not allowed
pub const E_JOB: u32 = 82;       // the job exists already, or this account is not a job
pub const E_STATE: u32 = 83;     // wrong state or time for this instruction
pub const E_TOKEN: u32 = 84;     // the token is not verified by knos-oidc, not GitHub's, or expired
pub const E_CLAIMS: u32 = 85;    // the token's claims do not allow this
pub const E_WORKFLOW: u32 = 86;  // the token is not from the workflow this instruction needs
pub const E_AUD: u32 = 87;       // the audience does not match
pub const E_PAYEE: u32 = 88;     // wrong destination, fee or refund account, or the payee has no bound wallet
pub const E_DEVNET: u32 = 89;    // devnet builds only
pub const E_RATE: u32 = 90;      // the faucet: one use per repository per minute, in the order GitHub issued the tokens
pub const E_REPLAY: u32 = 91;    // this token was used already, or is not newer than the last one used here: a token works once
pub const E_SPENDER: u32 = 92;   // the token's repository owner or actor may not spend this Balance
pub const E_CAP: u32 = 93;       // more than the Balance's cap per job
pub const E_FUNDS: u32 = 94;     // the Balance does not hold that much
pub const E_MINT: u32 = 95;      // the mint or the token program is not accepted
pub const E_PAUSED: u32 = 96;    // new funding is paused
pub const E_GUARDIAN: u32 = 97;  // not the guardian
pub const E_BALANCE: u32 = 98;   // the Balance exists already, is not a Balance, or the signer is not its authority
pub const E_FAUCET: u32 = 99;    // a faucet Balance cannot withdraw
pub const E_LIMIT: u32 = 100;    // more than the Balance's limit for one day or in total
pub const E_ORDER: u32 = 101;    // the order exists already, or this account is not an order
pub const E_PLAN: u32 = 102;     // not FEE_OWNER, or a plan rate or expiry that is not allowed
pub const E_LATER: u32 = 103;    // an order that is both standing and has a holdback is not paid: its money goes back at the deadline

#[cfg(not(feature = "no-entrypoint"))]
solana_program::entrypoint!(process);

#[cfg(not(feature = "no-entrypoint"))]
solana_security_txt::security_txt! {
    name: "knos-pay",
    project_url: "https://github.com/drexthealpha/Knos",
    contacts: "link:https://github.com/drexthealpha/Knos/security/advisories/new",
    policy: "https://github.com/drexthealpha/Knos/blob/main/SECURITY.md",
    source_code: "https://github.com/drexthealpha/Knos"
}

/// `bps` basis points of an amount, rounded down, without overflow.
pub fn bps_of(amount: u64, bps: u64) -> u64 { amount / 10_000 * bps + amount % 10_000 * bps / 10_000 }
/// The fee of a job's payment (2.0), taken out of the amount: FEE_BPS of it, at least FEE_MIN of a whole unit of the
/// mint, never more than the amount.
pub fn fee_of(amount: u64, decimals: u8) -> u64 { bps_of(amount, FEE_BPS).max(state::units(FEE_MIN, decimals)).min(amount) }
/// The fee of an order (2.1), paid by the funder on top of the amount. Marginal, in whole units of the mint: `bps`
/// (FEE_BPS, or the owner's Plan) of the first FEE_TIER_1 of the amount, FEE_BPS_2 of what lies between FEE_TIER_1 and
/// FEE_TIER_2, FEE_BPS_3 of what lies above; each part rounded down; at least ORDER_FEE_MIN; no cap. A Plan lowers
/// the first tier's rate only. Never more than 2.5% of the amount above the floor, so amount + fee fits a u64 for
/// every amount the program takes.
pub fn order_fee(amount: u64, bps: u64, decimals: u8) -> u64 {
    let (t1, t2) = (state::units(FEE_TIER_1, decimals), state::units(FEE_TIER_2, decimals));
    let first = amount.min(t1);
    let second = amount.min(t2) - first;
    let third = amount - first - second;
    (bps_of(first, bps) + bps_of(second, FEE_BPS_2) + bps_of(third, FEE_BPS_3)).max(state::units(ORDER_FEE_MIN, decimals))
}
/// Whether the record counts a payment in this mint as real money.
pub fn counted(mint: &Pubkey) -> bool { *mint == USDC_DEVNET || *mint == USDC_MAINNET || Some(*mint) == TEST_USDC }

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let (&tag, rest) = data.split_first().ok_or(ProgramError::InvalidInstructionData)?;
    let now = Clock::get()?.unix_timestamp;
    match tag {
        0 => fund::open_balance(program_id, accounts, rest),
        1 => fund::set_balance(program_id, accounts, rest),
        2 => fund::withdraw(program_id, accounts, rest),
        3 => fund::fund_balance(program_id, accounts, rest, now),
        4 => fund::fund_wallet(program_id, accounts, rest, now),
        5 => pay::pay(program_id, accounts, rest, now),
        6 => pay::settle(program_id, accounts, rest, now),
        7 => pay::refund(program_id, accounts, rest, now),
        8 => pay::bind(program_id, accounts, rest, now),
        9 => fund::pause(program_id, accounts, rest, now),
        10 => fund::init_faucet(program_id, accounts, rest),
        11 => fund::faucet_open(program_id, accounts, rest, now),
        12 => fund::version(rest),
        13 => fund::set_balance_x(program_id, accounts, rest),
        14 => fund::set_plan(program_id, accounts, rest, now),
        15 => order::fund_order_wallet(program_id, accounts, rest, now),
        16 => order::fund_order_balance(program_id, accounts, rest, now),
        17 => order_pay::pay_order(program_id, accounts, rest, now),
        18 => order_terms::release(program_id, accounts, rest, now),
        19 => order_terms::revert(program_id, accounts, rest, now),
        20 => order_terms::reserve(program_id, accounts, rest, now),
        21 => order_terms::cancel(program_id, accounts, rest, now),
        22 => order_pay::refund_order(program_id, accounts, rest, now),
        23 => order::top_up(program_id, accounts, rest, now),
        24 => order_terms::assign(program_id, accounts, rest),
        25 => order_judge::bind_org(program_id, accounts, rest, now),
        26 => order_pay::settle_order(program_id, accounts, rest, now),
        27 => order_terms::close_marker(program_id, accounts, rest, now),
        _ => Err(ProgramError::InvalidInstructionData),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_fee_is_two_and_a_half_percent_with_a_floor_and_never_more_than_the_amount() {
        for (amount, fee) in [(0, 0), (1, 1), (49_999, 49_999), (50_000, 50_000), (1_000_000, 50_000), (2_000_000, 50_000), (2_000_040, 50_001),
                              (5_000_000, 125_000), (500_000_000, 12_500_000), (100_000_000_000, 2_500_000_000), (u64::MAX, u64::MAX / 10_000 * 250 + (u64::MAX % 10_000) * 250 / 10_000)] {
            assert_eq!(fee_of(amount, 6), fee, "{amount}");
            assert!(fee_of(amount, 6) <= amount);
        }
        // the floor is 0.05 of a whole unit, whatever the mint's decimals
        assert_eq!((fee_of(1_000_000_000, 9), fee_of(100, 2), fee_of(3, 0), fee_of(1_000_000, 9)), (50_000_000, 5, 0, 1_000_000));
    }

    #[test]
    fn an_orders_fee_is_on_top_in_three_marginal_tiers_with_a_floor_of_forty_cents_and_no_cap() {
        const U: u64 = 1_000_000;   // one whole unit of a 6-decimal mint
        for (amount, bps, fee) in [
            // the floor, and where 2.5% passes it
            (0, 250, 400_000), (5 * U, 250, 400_000), (16 * U, 250, 400_000), (16 * U + 40, 250, 400_001), (100 * U, 250, 2_500_000),
            // the edge of the first tier: 2.5% of 1,000 is 25.00, and the unit after it is charged 1%
            (1_000 * U - 1, 250, 24_999_999), (1_000 * U, 250, 25 * U), (1_000 * U + 99, 250, 25 * U), (1_000 * U + 100, 250, 25 * U + 1),
            (1_001 * U, 250, 25 * U + 10_000), (2_000 * U, 250, 35 * U),
            // the edge of the second: 25 + 1% of 49,000 = 515.00, and the unit after it is charged 0.5%
            (50_000 * U - 1, 250, 515 * U - 1), (50_000 * U, 250, 515 * U), (50_000 * U + 199, 250, 515 * U), (50_000 * U + 200, 250, 515 * U + 1),
            (50_001 * U, 250, 515 * U + 5_000),
            // the most an order holds: 515 + 0.5% of 50,000 = 765.00; and no cap beyond it
            (100_000 * U, 250, 765 * U), (1_000_000 * U, 250, 5_265 * U),
            // a Plan lowers the first tier and nothing else
            (100 * U, 50, 500_000), (1_000 * U, 50, 5 * U), (1_000 * U, 150, 15 * U), (2_000 * U, 50, 15 * U), (50_000 * U, 150, 505 * U),
            (100_000 * U, 50, 745 * U), (16 * U, 50, 400_000),
        ] {
            assert_eq!(order_fee(amount, bps, 6), fee, "{amount} {bps}");
        }
        // every u64, without overflow: the three parts are parts of the amount
        assert_eq!(order_fee(u64::MAX, 250, 6), 25 * U + 490 * U + bps_of(u64::MAX - 50_000 * U, 50));
        // the tiers and the floor are whole units of the mint, whatever its decimals
        assert_eq!((order_fee(5_000_000_000, 250, 9), order_fee(500, 250, 2), order_fee(100, 250, 0)), (400_000_000, 40, 2));
        assert_eq!((order_fee(2_000_000_000_000, 250, 9), order_fee(200_000, 250, 2), order_fee(100_000, 250, 0), order_fee(60_000, 250, 0)),
                   (35_000_000_000, 3_500, 765, 565));
        const { assert!(TIP_FIRST <= ORDER_FEE_MIN && TIP <= TIP_FIRST && PLAN_BPS_MIN <= FEE_BPS && ORDER_MIN_AMOUNT <= MAX_AMOUNT) };
        const { assert!(FEE_TIER_1 < FEE_TIER_2 && FEE_TIER_2 <= MAX_AMOUNT && FEE_BPS_3 <= FEE_BPS_2 && FEE_BPS_2 <= FEE_BPS) };
        assert!(counted(&USDC_DEVNET) && counted(&USDC_MAINNET) && !counted(&FEE_OWNER));
    }

    #[test]
    fn the_bounds_are_the_ones_the_design_fixes() {
        assert_eq!((MIN_AMOUNT, MAX_AMOUNT, MAX_WORK, HOLD, PAUSE_MAX, MAX_TERMS), (1_000_000, 100_000_000_000, 7_776_000, 15_552_000, 604_800, 600));
        assert!(CLAIM_REF.ends_with(b"/.github/workflows/claim.yml@") && knos_oidc::claims::is_hex(CLAIM_SHA, 40));
        const { assert!(TOKEN_LIFE >= 300 && TOKEN_AHEAD >= CLOCK_SLACK) };
    }
}
#[cfg(any(kani, test))] mod proofs; // the fee and conservation arithmetic, for `cargo kani` and `cargo test`: not in the program
