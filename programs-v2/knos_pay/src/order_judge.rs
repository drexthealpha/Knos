//! Who may sign a payment of a work order (2.1): the JUDGES. This is the rule that decides who can move an order's
//! money, so it is one function (`judge`) that reads only what GitHub signed, and everything it does not name is
//! refused.
//!
//! Every judge's token is from the workflows the order pinned at funding: `job_workflow_ref` is in the order's
//! workflows repository (its sha256 is in the order) and `job_workflow_sha` is the order's commit, which fixes the
//! content of the file that ran. The run was on a GitHub-hosted runner (gh.rs requires it of every token), so the
//! steps that asked GitHub for the token were that file's and nobody's own machine; and it was the run's first
//! attempt, because a re-run keeps the first actor's name whoever starts it. Then one of:
//!   a. OWN      the run was in the order's own repository (`repository_id`), its prove.yml: as a 2.0 job.
//!   b. NEUTRAL  the order allows it (flag NEUTRAL, fixed at funding) and the run is attest.yml, started BY HAND
//!               (`workflow_dispatch`) by the account that owns the repository it ran in (`repository_owner_id` ==
//!               `actor_id`). attest.yml reads GitHub's public record of the pull request and signs only what that
//!               record supports, whoever starts it; a personal account cannot give a machine of its own the
//!               GitHub-hosted label; and the caller's file decides only when the pinned file runs, never what it
//!               does. So the seller can ask for his payment himself, and a buyer who deletes his workflow, or his
//!               repository, no longer withholds it. A push, a schedule and a call from another workflow's event are
//!               refused: only a person who owns the repository and started the run answers for it. A PRIVATE
//!               order has no public record to read, so no neutral run pays one.
//!   c. JUDGE REPOSITORY  the run was in the repository the order named as its judge (`judge_repo_id`, fixed at
//!               funding), its prove.yml or attest.yml. This is how a PRIVATE order is paid: its own repository is
//!               not on chain, so no run there can be told; a repository its funder chose attests for it, and that
//!               repository's id is the only one the order shows.
//!   d. ARBITER  the order named one at funding (`arbiter_id`), and the token is his RULING: audience
//!               knos3:rule:<order address>:<payees>, from attest.yml started by hand by the arbiter in a repository
//!               he owns. It pays the payees it names their shares (the same `id.bps.address` list as a pay token's),
//!               and needs no pull request: the two sides did not agree, and the person both accepted when the order
//!               was funded decides. A ruling is only ever the arbiter's: no other judge's run signs one, and with
//!               any other audience the arbiter is whoever else he is to the order. He is not a side: a Balance's
//!               order cannot name its funding commenter or its owner (refused at funding), and a ruling cannot name
//!               the arbiter among its payees. It may name the funder: a ruling can go the buyer's way.
//!
//!   e. AUTO     the order allows it (flag AUTO, fixed at funding, and only with mode 1: paid by the black-box suite),
//!               and the token's audience is knos3:auto:<order address>:<head sha>:<terms hash hex>:1:<pr>:<payee>:
//!               the order's own repository's prove.yml (as judge a) ran the acceptance bundle the terms hash names
//!               against that head of an OPEN, unmerged pull request, as a separate process, and it passed. It pays
//!               one payee, the pull request's author, whole. Nobody merges, assigns or comments first: the funder
//!               said so when he funded, in the options GitHub or his own wallet signed.
//!               WHAT THE BUYER TRUSTS in this mode: the pinned suite at the pinned commit. That is, the workflow
//!               file at the order's `wf_sha` (it decides that the bundle is black-box, that the head is still the
//!               pull request's, that the changed paths are within the terms' limits, and who the author is) and
//!               the acceptance bundle whose hash is in the terms. Nothing a maintainer does: no merge, no review,
//!               no label, no comment is asked, and none can stop it short of the deadline or a Cancel's notice.
//!               A pull request that fools the suite is paid; a holdback with a warranty keeps part of the money
//!               where a challenge (Revert, order_terms.rs) can still return it.
//!               The first passing pull request wins: the payment closes the order (or leaves it in WARRANTY), and a
//!               second token finds nothing OPEN. While the order is reserved, only its taker's pull request is paid
//!               this way. An order that is not AUTO takes no such token, whoever signs it.
//!
//! A COMMAND about an order (`command`, called by Reserve and Cancel) is not a judgement of work, and a judge's run
//! does not mint it: a person asks for it, by a comment that the order's repository answers with its COMMAND job, the
//! pinned fund.yml. So a command's token is from the pinned workflows at the order's commit, a first attempt, and
//!   - run in the order's own repository, its fund.yml (the comment) or its prove.yml; or
//!   - for a NEUTRAL order that is not PRIVATE, attest.yml started by hand by the account that owns the repository it
//!     ran in, exactly as judge b's (Reserve takes this one, Cancel does not).
//!
//! The judge repository and the arbiter sign no command. Who the person must be is the instruction's own rule: the
//! taker a take token names (Reserve), the funder or the Balance's owner (Cancel), always the token's `actor_id`.
//!
//! A PRIVATE order from a Balance (`funded`, called by FundOrderBalance). The fund token is public, as every token
//! is, so its audience names neither the repository nor the issue: `issue` is 0 and where a public order's audience
//! carries its terms hash, a private one's carries sha256(scope || terms hash). The instruction's data is those 64
//! bytes, scope then terms hash, in place of the terms JSON: GitHub's signature fixes both, and a relayer cannot put
//! the order at another address. The token must come from fund.yml in the judge repository the options name, and
//! pass every rule of the Balance (its owner, its spenders, its side account's repositories and limits) as that
//! repository. The order stores zero as repository and issue, the scope, and the terms hash; no terms are logged.
//!
//! A KEY THAT IS NOT GITHUB'S (`token`, called by PayOrder). Every instruction of this program takes only tokens that
//! a key of GitHub's verified (gh::github): a token under a PRIVATE key (knos-oidc's RegisterPrivateKey: any wallet,
//! no attestation) or under a registered issuer's key is refused, whatever it claims. One exception, for a company
//! whose own server no public runner can reach: PayOrder takes a pay token or a ruling under a private key when
//!   - the order is PRIVATE (so it said at funding that its attestor is its funder's own), and
//!   - it was funded from a Balance, and the wallet that registered the key is the wallet that opened that Balance:
//!     the order's `source` is the address ["bal", owner id, registrant, mint] derives.
//!
//! The token is then the word of the wallet whose money it pays out, and of nobody else's money. It is judged like
//! any token: the same pinned workflows, the order's judge repository, a first attempt, a GitHub-hosted runner in
//! its claims. It is never a ruling: the arbiter is someone else, and only GitHub's signature says who started a run.
//! FundOrderBalance takes GitHub's tokens only, so the order itself was funded on GitHub's signature.
//!
//! 25 BindOrg  relayer(s,w) bind_token key bind(w) system used(w)          no data
//!             An ORGANISATION's wallet, in the account a person's is, ["bind", id]: a payee id that is an
//!             organisation is then paid like any other (a bot's pull request, paid to the organisation that runs
//!             it). The token: audience knos3:bind:<address>; the pinned claim workflow (CLAIM_REF at CLAIM_SHA or
//!             CLAIM_SHA_ORG); `repository` ends with "/knos-claim"; `workflow_dispatch`, first attempt; and
//!             `repository_owner_id` is not `actor_id`: an organisation never starts a run, a member does, by hand,
//!             and who may is the organisation's own rule (write access to its knos-claim). Sets
//!             ["bind", repository_owner_id]; one that BindOrg set is replaced only by a token with a later `iat`.
//!             GitHub's claims do not say whether an owner is a person or an organisation, so a person who gave
//!             someone write access to his own knos-claim looks the same. Therefore BindOrg never replaces a Bind
//!             that Bind (8) wrote: what a person bound himself, only he rebinds. (A Bind made here says so, in
//!             bytes Bind does not write: BD_ORG, and the `iat` it was made with, which stops matching the moment
//!             Bind rewrites the account.) Logs knos3:bound org= wallet= by=.
use crate::{err, gh::*, order::*, order_pay::{pay_aud_as, pay_order_aud, payees_of, Judge, PayAud}, state::*, *};
use knos_oidc::claims::{self, parts};
use solana_program::{account_info::AccountInfo, entrypoint::ProgramResult, hash::hashv, msg, program_error::ProgramError, pubkey::Pubkey};

/// The pinned workflow whose run anyone may start for himself (judge b).
pub const ATTEST: &[u8] = b"attest.yml";
/// The pinned workflow that proves an order in its own repository (judge a).
pub const PROVE: &[u8] = b"prove.yml";

/// The pinned workflow of the COMMAND job: it funds, and it answers what a person asks of an order by comment.
pub const FUND: &[u8] = b"fund.yml";

/// How the audience of a ruling starts. `judge` answers Arbiter for these audiences and for no other.
pub const RULE: &[u8] = b"knos3:rule:";
/// How the audience of an AUTO order's unmerged payment starts. `judge` answers Auto for these and for no other.
pub const AUTO: &[u8] = b"knos3:auto:";

/// The run was started by hand by the account that owns the repository it ran in: a person, in a repository of his.
/// An organisation never starts a run, so a run in an organisation's repository is not this.
fn by_hand(g: &Gh) -> bool { g.event == b"workflow_dispatch" && g.actor_id != 0 && g.actor_id == g.owner_id }

/// Which judge of this order signed this token, or a refusal: E_WORKFLOW when the token is not from the pinned
/// workflows or not from the file its judge runs, E_CLAIMS when no judge of this order is in its claims.
pub fn judge(o: &Order, g: &Gh) -> Result<Judge, ProgramError> {
    if g.wf_repo != o.wf_repo || g.wf_sha[..] != o.wf_sha[..] { return Err(err(E_WORKFLOW)); }
    if !g.first_attempt { return Err(err(E_CLAIMS)); }
    // d. a ruling: the arbiter's or nobody's
    if g.aud.starts_with(RULE) {
        if g.wf_file != ATTEST { return Err(err(E_WORKFLOW)); }
        let named = o.arbiter_id != 0 && o.arbiter_id != o.funder_id && o.arbiter_id != o.owner_id;
        return if named && by_hand(g) && g.actor_id == o.arbiter_id { Ok(Judge::Arbiter) } else { Err(err(E_CLAIMS)) };
    }
    let own = o.repo != 0 && g.repo_id == o.repo;
    // e. paid unmerged: only an order funded AUTO, and only its own repository's prove.yml
    if g.aud.starts_with(AUTO) {
        if !o.is(F_AUTO) || !own { return Err(err(E_CLAIMS)); }
        return if g.wf_file == PROVE { Ok(Judge::Auto) } else { Err(err(E_WORKFLOW)) };
    }
    if own && g.wf_file == PROVE { return Ok(Judge::Own); }
    let named = o.judge_repo_id != 0 && g.repo_id == o.judge_repo_id;
    if named && (g.wf_file == PROVE || g.wf_file == ATTEST) { return Ok(Judge::Private); }
    let neutral = o.is(F_NEUTRAL) && !o.is(F_PRIVATE) && by_hand(g);
    if neutral && g.wf_file == ATTEST { return Ok(Judge::Neutral); }
    // a run that would be a judge's, but of another file of the pinned workflows
    Err(err(if own || named || neutral { E_WORKFLOW } else { E_CLAIMS }))
}

/// Whose run signed a COMMAND about this order (Reserve, Cancel), or a refusal with `judge`'s codes. Own: the order's
/// own repository, its fund.yml or prove.yml. Neutral: attest.yml by hand in the runner's own repository, for an order
/// that allows it. Nothing else: the judge repository and the arbiter judge work, they do not take or cancel it.
pub fn command(o: &Order, g: &Gh) -> Result<Judge, ProgramError> {
    if g.wf_repo != o.wf_repo || g.wf_sha[..] != o.wf_sha[..] { return Err(err(E_WORKFLOW)); }
    if !g.first_attempt { return Err(err(E_CLAIMS)); }
    let own = o.repo != 0 && g.repo_id == o.repo;
    if own && (g.wf_file == FUND || g.wf_file == PROVE) { return Ok(Judge::Own); }
    let neutral = o.is(F_NEUTRAL) && !o.is(F_PRIVATE) && by_hand(g);
    if neutral && g.wf_file == ATTEST { return Ok(Judge::Neutral); }
    Err(err(if own || neutral { E_WORKFLOW } else { E_CLAIMS }))
}

/// The token of a PayOrder: GitHub's, or for a PRIVATE order of a Balance one under a private key that the wallet
/// which opened that Balance registered (the module documentation says why). The Balance is not read: its address is
/// derived from the order's owner id and mint and the key's registrant, and must be the order's source.
pub fn token(program_id: &Pubkey, o: &Order, tok: &AccountInfo, key: &AccountInfo, now: i64) -> Result<Gh, ProgramError> {
    let g = token_of(tok, key, now, |registrant| {
        o.kind == 1 && o.is(F_PRIVATE)
            && Pubkey::find_program_address(&[b"bal", &o.owner_id.to_le_bytes(), registrant, o.mint.as_ref()], program_id).0 == o.source
    })?;
    // a ruling is the arbiter's word, and only GitHub says who started a run: the funder's own key signs none in his name
    if g.aud.starts_with(RULE) && knos_oidc::is_private(&tok.try_borrow_data()?) { return Err(err(E_TOKEN)); }
    Ok(g)
}

/// What a judge's token pays, read from its audience. A pay token (judges a, b, c) names the order, the commit, the
/// terms, the mode, the pull request and the payees (`pay_order_aud`). A ruling (judge d) names the order and the
/// payees: knos3:rule:<order address>:<payees>. It is returned with the order's own terms and mode and pull request 0,
/// so PayOrder checks its order address exactly as it checks a pay token's. The arbiter is not one of his payees.
/// An AUTO order's unmerged payment (judge e) names what a pay token names, under knos3:auto: one payee, the pull
/// request's author; and while the order is reserved (`now` within the reservation) that payee is the taker.
pub fn audience(o: &Order, judge: Judge, aud: &[u8], now: i64) -> Result<PayAud, ProgramError> {
    if judge == Judge::Auto {
        let a = pay_aud_as(aud, b"auto")?;
        if a.payees.len() != 1 { return Err(err(E_AUD)); }
        if o.reserved_by != 0 && now <= o.reserved_until && a.payees[0].id != o.reserved_by { return Err(err(E_CLAIMS)); }
        return Ok(a);
    }
    if judge != Judge::Arbiter { return pay_order_aud(aud); }
    let bad = || err(E_AUD);
    let [k, r, order, list] = parts::<4>(aud).ok_or_else(bad)?;
    if k != b"knos3" || r != b"rule" { return Err(bad()); }
    let payees = payees_of(list)?;
    if payees.iter().any(|p| p.id == o.arbiter_id) { return Err(err(E_CLAIMS)); }
    Ok(PayAud { order: Pubkey::new_from_array(claims::b58_32(order).ok_or_else(bad)?), terms: o.terms, mode: o.mode, pr: 0, payees })
}

/// What FundOrderBalance creates: the order's repository and issue as it stores and logs them, its scope, its terms
/// hash, and the terms JSON to log (none for a private order).
pub struct Funded<'a> { pub repo: u64, pub issue: u64, pub scope: [u8; 32], pub terms: [u8; 32], pub json: Option<&'a [u8]> }

/// HOOK of FundOrderBalance, once the token is a fund token of this Balance and its options are within bounds.
/// A public order: `data` is the terms JSON whose hash the audience carries, and the order is the token's
/// repository's. A PRIVATE order: see the module documentation. Either: the arbiter it names is not its funder.
pub fn funded<'a>(opts: &Opts, f: &OrderFundAud, g: &Gh, data: &'a [u8]) -> Result<Funded<'a>, ProgramError> {
    // an arbiter decides between the funder and the payees: he is not the commenter who funds, nor the owner whose
    // Balance pays (`may_spend` has required the token's owner to be the Balance's)
    if opts.arbiter_id != 0 && (opts.arbiter_id == g.actor_id || opts.arbiter_id == g.owner_id) { return Err(err(E_TERMS)); }
    if !opts.salted {
        if crate::fund::terms_hash(data)? != f.terms { return Err(err(E_TERMS)); }
        return Ok(Funded { repo: g.repo_id, issue: f.issue, scope: public_scope(g.repo_id, f.issue), terms: f.terms, json: Some(data) });
    }
    if data.len() != 64 || f.issue != 0 || hashv(&[data]).to_bytes() != f.terms { return Err(err(E_TERMS)); }
    // funded where it will be judged: the comment was in the judge repository (opts_of required one of a private order)
    if g.repo_id != opts.judge_repo_id { return Err(err(E_CLAIMS)); }
    Ok(Funded { repo: 0, issue: 0, scope: data[..32].try_into().unwrap(), terms: data[32..].try_into().unwrap(), json: None })
}

/// The claim workflow's commit that BindOrg accepts beside CLAIM_SHA: its later commit, which takes `kind: org` and
/// mints knos3:bind:<address> (programs-v2/program_ids.json, "claim_sha_org"). What Bind accepts is not touched by it.
pub const CLAIM_SHA_ORG: &[u8; 40] = b"212f9eb5f584eb6f8cd2d6673878132fc0011e27";
// In a Bind, two fields only BindOrg writes (Bind leaves them as they are):
pub const BD_ORG: usize = 2;        // 1: BindOrg wrote this Bind
pub const BD_ORG_IAT: usize = 3;    // [u8; 5]: the low bytes of the `iat` BindOrg wrote it with

/// Whether BindOrg wrote the Bind as it stands: its mark is there and is of the `iat` the account holds. Bind (8)
/// rewrites the `iat` with a later one and not the mark, so a Bind a person made himself is never this.
fn org_made(d: &[u8]) -> bool { d[BD_ORG] == 1 && d[BD_ORG_IAT..BD_ORG_IAT + 5] == d[BD_IAT..BD_IAT + 5] }

/// knos3:bind:<address>
pub fn org_bind_aud(aud: &[u8]) -> Result<Pubkey, ProgramError> {
    let [k, b, address] = parts::<3>(aud).ok_or_else(|| err(E_AUD))?;
    if k != b"knos3" || b != b"bind" { return Err(err(E_AUD)); }
    Ok(Pubkey::new_from_array(claims::b58_32(address).ok_or_else(|| err(E_AUD))?))
}

/// 25 BindOrg: binds a wallet to an organisation. See the module documentation.
pub fn bind_org(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, tok, key, bind, sys, used] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
    let g = github(tok, key, now)?;
    let sha_ok = g.wf_sha[..] == CLAIM_SHA[..] || g.wf_sha[..] == CLAIM_SHA_ORG[..] || TEST_CLAIM_SHA.is_some_and(|t| g.wf_sha[..] == t[..]);
    if !g.wf_ref.starts_with(CLAIM_REF) || !sha_ok { return Err(err(E_WORKFLOW)); }
    // the repository is the owner's knos-claim, the owner did not start the run (so it is not a person binding his
    // own wallet: that is Bind), and whoever did started it by hand, once
    let org = g.owner_id != 0 && g.actor_id != 0 && g.owner_id != g.actor_id;
    let named = g.repository.as_deref().is_some_and(|r| r.ends_with(b"/knos-claim"));
    let started = g.first_attempt && g.event == b"workflow_dispatch";
    if !org || !named || !started { return Err(err(E_CLAIMS)); }
    let wallet = org_bind_aud(&g.aud)?;
    let (first, bump) = open(program_id, relayer, bind, sys, BIND_LEN, &[b"bind", &g.owner_id.to_le_bytes()], E_ACCOUNTS)?;
    if !first {
        // what a person bound himself stays his; a later token rebinds an organisation, the same or an older one does nothing
        let d = bind.try_borrow_data()?;
        if !org_made(&d) { return Err(err(E_CLAIMS)); }
        if g.iat <= i64_at(&d, BD_IAT) { return Err(err(E_REPLAY)); }
    }
    mark_used(program_id, relayer, used, sys, &sig_hash(tok)?, USED, false)?;
    let mut d = bind.try_borrow_mut_data()?;
    d[BD_VERSION] = 1; d[BD_BUMP] = bump;
    put_u64(&mut d, BD_USER, g.owner_id); put_key(&mut d, BD_WALLET, &wallet); put_i64(&mut d, BD_IAT, g.iat);
    d[BD_ORG] = 1;
    d.copy_within(BD_IAT..BD_IAT + 5, BD_ORG_IAT);
    msg!("knos3:bound org={} wallet={} by={}", g.owner_id, b58(&wallet), g.actor_id);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const REPO: u64 = 987_654_321;
    const JUDGE_REPO: u64 = 31_313_131;
    const ARBITER: u64 = 77;
    const SELLER: u64 = 1_234_567;

    fn order(flags: u8, repo: u64, judge_repo_id: u64, arbiter_id: u64) -> Order {
        let z = Pubkey::new_from_array([0; 32]);
        Order { state: OPEN, mode: 0, kind: 1, flags, decimals: 6, reserve_days: 0, repo, issue: 7, scope: [0; 32], seq: 0, holdback_bps: 0, kill_bps: 0,
                fee_bps: 250, amount: 5_000_000, fee: 400_000, rate: 0, paid: 0, deadline: 100, not_before: 0, hold_until: 0, warranty_s: 0, reserved_by: 0,
                reserved_until: 0, cancel_at: 0, payee: 0, funder_id: 555_000, owner_id: 424_242, arbiter_id, judge_repo_id, source: z, refund_to: z,
                rent_to: z, mint: z, terms: [0xab; 32], wf_repo: [1; 32], wf_sha: [b'c'; 40] }
    }
    /// A token of the pinned workflows: `file`, run in `repo` owned by `owner`, started by `actor` on `event`.
    fn run(file: &str, repo: u64, owner: u64, actor: u64, event: &str, aud: &str) -> Gh {
        Gh { repo_id: repo, owner_id: owner, actor_id: actor, iat: 1, wf_ref: Vec::new(), wf_repo: [1; 32], wf_file: file.as_bytes().to_vec(), wf_sha: vec![b'c'; 40],
             aud: aud.as_bytes().to_vec(), event: event.as_bytes().to_vec(), repository: None, first_attempt: true }
    }
    fn says(o: &Order, g: &Gh) -> Result<Judge, u32> {
        judge(o, g).map_err(|e| match e { ProgramError::Custom(c) => c, _ => 0 })
    }

    #[test]
    fn each_judge_is_named_by_the_claims_and_everything_else_is_refused() {
        let (pay, rule, hand) = ("knos3:pay:x", "knos3:rule:x", "workflow_dispatch");
        let all = order(F_NEUTRAL, REPO, JUDGE_REPO, ARBITER);
        let plain = order(0, REPO, 0, 0);
        let private = order(F_PRIVATE | F_NEUTRAL, 0, JUDGE_REPO, ARBITER);
        // a. the order's own repository, its prove.yml, on any event
        for o in [&all, &plain] {
            assert_eq!(says(o, &run("prove.yml", REPO, 424_242, SELLER, "pull_request_target", pay)), Ok(Judge::Own));
            assert_eq!(says(o, &run("fund.yml", REPO, 424_242, SELLER, "issue_comment", pay)), Err(E_WORKFLOW));
        }
        assert_eq!(says(&plain, &run("attest.yml", REPO, 424_242, 424_242, hand, pay)), Err(E_WORKFLOW));
        assert_eq!(says(&private, &run("prove.yml", 0, 424_242, SELLER, "pull_request_target", pay)), Err(E_CLAIMS));    // repository id 0 is nobody's
        // b. attest.yml, by hand, by the owner of the repository it ran in, for an order that allows it
        assert_eq!(says(&all, &run("attest.yml", 5, SELLER, SELLER, hand, pay)), Ok(Judge::Neutral));
        assert_eq!(says(&all, &run("attest.yml", REPO, 424_242, 424_242, hand, pay)), Ok(Judge::Neutral));
        for (g, want) in [(run("attest.yml", 5, SELLER, SELLER, hand, pay), E_CLAIMS), (run("prove.yml", 5, SELLER, SELLER, hand, pay), E_CLAIMS)] {
            assert_eq!(says(&plain, &g), Err(want));
            assert_eq!(says(&private, &g), Err(want));
        }
        for g in [run("attest.yml", 5, 9, SELLER, hand, pay), run("attest.yml", 5, SELLER, 9, hand, pay), run("attest.yml", 5, 0, 0, hand, pay),
                  run("attest.yml", 5, SELLER, SELLER, "push", pay), run("attest.yml", 5, SELLER, SELLER, "workflow_call", pay),
                  run("attest.yml", 5, SELLER, SELLER, "", pay)] {
            assert_eq!(says(&all, &g), Err(E_CLAIMS));
        }
        assert_eq!(says(&all, &run("prove.yml", 5, SELLER, SELLER, hand, pay)), Err(E_WORKFLOW));
        // c. the judge repository, its prove.yml or attest.yml
        for o in [&all, &private] {
            assert_eq!(says(o, &run("prove.yml", JUDGE_REPO, 9, SELLER, "push", pay)), Ok(Judge::Private));
            assert_eq!(says(o, &run("attest.yml", JUDGE_REPO, 9, SELLER, "push", pay)), Ok(Judge::Private));
            assert_eq!(says(o, &run("fund.yml", JUDGE_REPO, 9, SELLER, "push", pay)), Err(E_WORKFLOW));
        }
        assert_eq!(says(&plain, &run("prove.yml", JUDGE_REPO, 9, SELLER, "push", pay)), Err(E_CLAIMS));
        assert_eq!(says(&plain, &run("prove.yml", 0, 9, SELLER, "push", pay)), Err(E_CLAIMS));          // no judge repository is not repository 0
        // d. a ruling: the arbiter's, from attest.yml, by hand, in a repository of his; and from nobody else's run
        for o in [&all, &private] {
            assert_eq!(says(o, &run("attest.yml", 5, ARBITER, ARBITER, hand, rule)), Ok(Judge::Arbiter));
            for g in [run("attest.yml", 5, SELLER, SELLER, hand, rule), run("attest.yml", 5, 9, ARBITER, hand, rule), run("attest.yml", 5, ARBITER, 9, hand, rule),
                      run("attest.yml", 5, ARBITER, ARBITER, "push", rule), run("attest.yml", JUDGE_REPO, 9, SELLER, "push", rule)] {
                assert_eq!(says(o, &g), Err(E_CLAIMS));
            }
            assert_eq!(says(o, &run("prove.yml", REPO, 424_242, SELLER, "pull_request_target", rule)), Err(E_WORKFLOW));
            assert_eq!(says(o, &run("prove.yml", 5, ARBITER, ARBITER, hand, rule)), Err(E_WORKFLOW));
        }
        assert_eq!(says(&plain, &run("attest.yml", 5, ARBITER, ARBITER, hand, rule)), Err(E_CLAIMS));
        assert_eq!(says(&order(0, REPO, 0, 555_000), &run("attest.yml", 5, 555_000, 555_000, hand, rule)), Err(E_CLAIMS));     // the funder
        assert_eq!(says(&order(0, REPO, 0, 424_242), &run("attest.yml", 5, 424_242, 424_242, hand, rule)), Err(E_CLAIMS));     // the Balance's owner
        // with a pay audience the arbiter is whoever else he is to the order
        assert_eq!(says(&order(0, REPO, 0, ARBITER), &run("attest.yml", 5, ARBITER, ARBITER, hand, pay)), Err(E_CLAIMS));
        assert_eq!(says(&all, &run("attest.yml", 5, ARBITER, ARBITER, hand, pay)), Ok(Judge::Neutral));
        // e. an unmerged payment: an AUTO order's own prove.yml, and nobody else's run; an order that is not AUTO takes none
        let (auto, unmerged) = (order(F_AUTO | F_NEUTRAL, REPO, JUDGE_REPO, ARBITER), "knos3:auto:x");
        assert_eq!(says(&auto, &run("prove.yml", REPO, 424_242, SELLER, "workflow_run", unmerged)), Ok(Judge::Auto));
        assert_eq!(says(&auto, &run("prove.yml", REPO, 424_242, SELLER, "workflow_run", pay)), Ok(Judge::Own));
        assert_eq!(says(&auto, &run("attest.yml", REPO, 424_242, 424_242, hand, unmerged)), Err(E_WORKFLOW));
        for g in [run("attest.yml", 5, SELLER, SELLER, hand, unmerged), run("prove.yml", JUDGE_REPO, 9, SELLER, "push", unmerged),
                  run("prove.yml", 5, SELLER, SELLER, hand, unmerged)] {
            assert_eq!(says(&auto, &g), Err(E_CLAIMS));
        }
        for o in [&all, &plain] {
            assert_eq!(says(o, &run("prove.yml", REPO, 424_242, SELLER, "workflow_run", unmerged)), Err(E_CLAIMS));
        }
        // always: the pinned repository and commit, and a first attempt
        for file in ["prove.yml", "attest.yml"] {
            let mut g = run(file, REPO, 424_242, 424_242, hand, pay);
            g.first_attempt = false;
            assert_eq!(says(&all, &g), Err(E_CLAIMS));
            let mut g = run(file, REPO, 424_242, 424_242, hand, pay);
            g.wf_sha = vec![b'd'; 40];
            assert_eq!(says(&all, &g), Err(E_WORKFLOW));
            let mut g = run(file, REPO, 424_242, 424_242, hand, pay);
            g.wf_repo = [2; 32];
            assert_eq!(says(&all, &g), Err(E_WORKFLOW));
        }
    }

    #[test]
    fn a_command_is_the_orders_own_fund_or_prove_run_or_a_neutral_run_by_hand() {
        let (take, hand, comment) = ("knos3:take:x:1:1", "workflow_dispatch", "issue_comment");
        let cmd = |o: &Order, g: &Gh| command(o, g).map_err(|e| match e { ProgramError::Custom(c) => c, _ => 0 });
        let all = order(F_NEUTRAL, REPO, JUDGE_REPO, ARBITER);
        let plain = order(0, REPO, 0, 0);
        let private = order(F_PRIVATE | F_NEUTRAL, 0, JUDGE_REPO, ARBITER);
        for o in [&all, &plain] {
            assert_eq!(cmd(o, &run("fund.yml", REPO, 424_242, SELLER, comment, take)), Ok(Judge::Own));
            assert_eq!(cmd(o, &run("prove.yml", REPO, 424_242, SELLER, "pull_request_target", take)), Ok(Judge::Own));
            assert_eq!(cmd(o, &run("claim.yml", REPO, 424_242, SELLER, comment, take)), Err(E_WORKFLOW));
            assert_eq!(cmd(o, &run("fund.yml", 5, 424_242, SELLER, comment, take)), Err(E_CLAIMS));        // another repository's command job
            assert_eq!(cmd(o, &run("fund.yml", 5, SELLER, SELLER, hand, take)), Err(if o.is(F_NEUTRAL) { E_WORKFLOW } else { E_CLAIMS }));
        }
        // a judge's fund.yml is still no judge: what PayOrder accepts did not widen
        assert_eq!(says(&all, &run("fund.yml", REPO, 424_242, SELLER, comment, "knos3:pay:x")), Err(E_WORKFLOW));
        // attest.yml by hand in the runner's own repository, only for an order that allows it and is not private
        assert_eq!(cmd(&all, &run("attest.yml", 5, SELLER, SELLER, hand, take)), Ok(Judge::Neutral));
        assert_eq!(cmd(&plain, &run("attest.yml", 5, SELLER, SELLER, hand, take)), Err(E_CLAIMS));
        assert_eq!(cmd(&plain, &run("attest.yml", REPO, 424_242, 424_242, hand, take)), Err(E_WORKFLOW));
        for g in [run("attest.yml", 5, 9, SELLER, hand, take), run("attest.yml", 5, SELLER, 9, hand, take), run("attest.yml", 5, SELLER, SELLER, "push", take),
                  run("attest.yml", 5, 0, 0, hand, take)] {
            assert_eq!(cmd(&all, &g), Err(E_CLAIMS));
        }
        // the judge repository and the arbiter sign no command; a private order (repository 0) has no command job
        for file in ["prove.yml", "attest.yml", "fund.yml"] {
            assert_eq!(cmd(&all, &run(file, JUDGE_REPO, 9, SELLER, "push", take)), Err(E_CLAIMS));
            assert_eq!(cmd(&private, &run(file, JUDGE_REPO, 9, SELLER, comment, take)), Err(E_CLAIMS));
            assert_eq!(cmd(&private, &run(file, 0, 9, SELLER, comment, take)), Err(E_CLAIMS));
        }
        assert_eq!(cmd(&private, &run("attest.yml", 5, SELLER, SELLER, hand, take)), Err(E_CLAIMS));
        assert_eq!(cmd(&all, &run("attest.yml", 5, ARBITER, ARBITER, hand, "knos3:rule:x")), Ok(Judge::Neutral));     // as anyone, never as arbiter
        // always: the pinned repository and commit, and a first attempt
        for (file, repo) in [("fund.yml", REPO), ("prove.yml", REPO), ("attest.yml", 5)] {
            let base = || run(file, repo, 424_242, 424_242, hand, take);
            let (mut again, mut commit, mut elsewhere) = (base(), base(), base());
            (again.first_attempt, commit.wf_sha, elsewhere.wf_repo) = (false, vec![b'd'; 40], [2; 32]);
            assert_eq!((cmd(&all, &again), cmd(&all, &commit), cmd(&all, &elsewhere)), (Err(E_CLAIMS), Err(E_WORKFLOW), Err(E_WORKFLOW)));
        }
    }

    #[test]
    fn a_ruling_names_the_order_and_payees_who_are_not_the_arbiter() {
        let o = order(0, REPO, 0, ARBITER);
        let (at, w) = (Pubkey::new_from_array([7; 32]), Pubkey::new_from_array([9; 32]));
        let a = audience(&o, Judge::Arbiter, format!("knos3:rule:{at}:5.7000.{w},6.3000.-").as_bytes(), 0).ok().unwrap();
        assert_eq!((a.order, a.terms, a.mode, a.pr, a.payees.len(), a.payees[0].id, a.payees[1].bps), (at, o.terms, o.mode, 0, 2, 5, 3000));
        let code = |aud: String, j: Judge| audience(&o, j, aud.as_bytes(), 0).err();
        assert!(code(format!("knos3:rule:{at}:{ARBITER}.10000.-"), Judge::Arbiter) == Some(err(E_CLAIMS)));
        assert!(code(format!("knos3:rule:{at}:5.5000.-,{ARBITER}.5000.-"), Judge::Arbiter) == Some(err(E_CLAIMS)));
        for bad in [format!("knos3:rule:{at}"), format!("knos3:rule:{at}:5.10000.-:x"), format!("knos2:rule:{at}:5.10000.-"), "knos3:rule:x:5.10000.-".to_string(),
                    format!("knos3:rule:{at}:5.9999.-"), format!("knos3:pay:{at}:{}:{}:0:7:5.10000.-", "a".repeat(40), "ab".repeat(32))] {
            assert!(code(bad.clone(), Judge::Arbiter) == Some(err(E_AUD)), "{bad}");
        }
        // an unmerged payment names one payee, and the taker while the order is reserved
        let auto = |list: &str| format!("knos3:auto:{at}:{}:{}:1:7:{list}", "a".repeat(40), "ab".repeat(32));
        assert!(audience(&o, Judge::Auto, auto("5.10000.-").as_bytes(), 0).is_ok());
        assert!(code(auto("5.5000.-,6.5000.-"), Judge::Auto) == Some(err(E_AUD)));
        assert!(code(auto("5.10000.-").replace("auto", "pay"), Judge::Auto) == Some(err(E_AUD)) && code(auto("5.10000.-"), Judge::Own) == Some(err(E_AUD)));
        let mut taken = order(0, REPO, 0, ARBITER);
        (taken.reserved_by, taken.reserved_until) = (6, 100);
        assert!(audience(&taken, Judge::Auto, auto("5.10000.-").as_bytes(), 100).err() == Some(err(E_CLAIMS)));
        assert!(audience(&taken, Judge::Auto, auto("6.10000.-").as_bytes(), 100).is_ok() && audience(&taken, Judge::Auto, auto("5.10000.-").as_bytes(), 101).is_ok());
        // every other judge signs a pay audience, and a ruling is not one
        for j in [Judge::Own, Judge::Neutral, Judge::Private] {
            assert!(code(format!("knos3:rule:{at}:5.10000.-"), j) == Some(err(E_AUD)));
            assert!(audience(&o, j, format!("knos3:pay:{at}:{}:{}:0:7:5.10000.-", "a".repeat(40), "ab".repeat(32)).as_bytes(), 0).is_ok());
        }
    }

    #[test]
    fn an_organisations_bind_is_told_from_a_persons_and_the_pins_are_commits() {
        let mut d = [0u8; BIND_LEN];
        assert!(!org_made(&d));
        put_i64(&mut d, BD_IAT, 1_790_000_000);
        d[BD_ORG] = 1;
        d.copy_within(BD_IAT..BD_IAT + 5, BD_ORG_IAT);
        assert!(org_made(&d));
        put_i64(&mut d, BD_IAT, 1_790_000_001);          // Bind rewrote it with a later token and left the mark
        assert!(!org_made(&d));
        const { assert!(BD_ORG > BD_BUMP && BD_ORG_IAT + 5 <= BD_USER) };
        assert!(claims::is_hex(CLAIM_SHA_ORG, 40));
        let w = Pubkey::new_from_array([9; 32]);
        assert!(org_bind_aud(format!("knos3:bind:{w}").as_bytes()) == Ok(w));
        for bad in [format!("knos2:bind:{w}"), format!("knos3:bind:{w}:x"), "knos3:bind:".to_string(), format!("knos3:rule:{w}")] {
            assert!(org_bind_aud(bad.as_bytes()).is_err(), "{bad}");
        }
    }
}
