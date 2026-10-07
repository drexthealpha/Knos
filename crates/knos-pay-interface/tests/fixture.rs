//! The crate against the Python client: every address, instruction and Order field in tests/fixtures/pay_interface.json
//! (written by scripts/pay_interface_fixture.py from src/knos/settle/v2/pay.py and a real order of the test build of
//! knos_pay) is rebuilt here from the same inputs and must come out byte for byte.
use knos_pay_interface::*;
use serde_json::Value;
use solana_program::{instruction::Instruction, pubkey::Pubkey};
use std::str::FromStr;

fn fixture() -> Value { serde_json::from_str(include_str!("fixtures/pay_interface.json")).unwrap() }
fn key(v: &Value) -> Pubkey { Pubkey::from_str(v.as_str().unwrap()).unwrap() }
fn unhex(v: &Value) -> Vec<u8> {
    let s = v.as_str().unwrap().as_bytes();
    s.chunks(2).map(|c| u8::from_str_radix(core::str::from_utf8(c).unwrap(), 16).unwrap()).collect()
}
fn n(v: &Value) -> u64 { v.as_u64().unwrap() }

/// The instruction as the fixture has it: (program, data, [(key, signer, writable)]).
fn same(ix: &Instruction, want: &Value) {
    assert_eq!(ix.program_id, key(&want["program"]), "{}", want["name"]);
    assert_eq!(ix.data, unhex(&want["data"]), "{}", want["name"]);
    let got: Vec<(Pubkey, bool, bool)> = ix.accounts.iter().map(|a| (a.pubkey, a.is_signer, a.is_writable)).collect();
    let metas: Vec<(Pubkey, bool, bool)> = want["accounts"].as_array().unwrap().iter()
        .map(|a| (key(&a[0]), a[1].as_bool().unwrap(), a[2].as_bool().unwrap())).collect();
    assert_eq!(got, metas, "{}", want["name"]);
}
fn named<'a>(f: &'a Value, name: &str) -> &'a Value {
    f["instructions"].as_array().unwrap().iter().find(|i| i["name"] == name).unwrap()
}
fn fund_of(f: &Value) -> FundOrder {
    let o = &f["opts"];
    let opts = Opts { flags: n(&o["flags"]) as u8, holdback_bps: n(&o["holdback_bps"]) as u16, warranty_days: n(&o["warranty_days"]) as u16,
                      kill_bps: n(&o["kill_bps"]) as u16, reserve_days: n(&o["reserve_days"]) as u8, rate: n(&o["rate"]), arbiter_id: n(&o["arbiter_id"]),
                      judge_repo_id: n(&o["judge_repo_id"]), salted: false };
    FundOrder { repo_id: n(&f["repo_id"]), issue: n(&f["issue"]), amount: n(&f["amount"]), mode: MERGE, work_s: n(&f["work_s"]) as i64,
                seq: n(&f["seq"]) as u32, opts, wf_repo: wf_repo_hash(f["wf_repo"].as_str().unwrap()),
                wf_sha: f["wf_sha"].as_str().unwrap().as_bytes().try_into().unwrap(), private_scope: None }
}

#[test]
fn the_ids_and_addresses_are_the_python_clients() {
    let f = fixture();
    assert_eq!((ID, FEE_OWNER), (key(&f["program"]), key(&f["fee_owner"])));
    assert_eq!(ID.to_string(), ID_STR);
    let (a, funder, mint) = (&f["addresses"], key(&f["funder"]), key(&f["mint"]));
    let s = scope(n(&f["repo_id"]), n(&f["issue"]));
    assert_eq!(s.to_vec(), unhex(&a["scope"]));
    let salt: [u8; 32] = unhex(&f["salt"]).try_into().unwrap();
    assert_eq!(private_scope(&salt, n(&f["repo_id"]), n(&f["issue"])).to_vec(), unhex(&a["private_scope"]));
    let at = order(&ID, &s, &funder, n(&f["seq"]) as u32);
    assert_eq!((auth(&ID), pause(&ID), at, ov(&ID, &at), ata(&funder, &mint, &TOKEN)),
               (key(&a["auth"]), key(&a["pause"]), key(&a["order"]), key(&a["ov"]), key(&a["ata"])));
    assert_eq!(terms_hash(f["terms"].as_str().unwrap().as_bytes()).to_vec(), unhex(&f["terms_hash"]));
    assert_eq!(fund_of(&f).opts.to_bytes().to_vec(), unhex(&f["opts_hex"]));
    for row in f["fees"].as_array().unwrap() {
        assert_eq!(order_fee(n(&row[0]), n(&row[1]), n(&row[2]) as u8), n(&row[3]), "{row}");
    }
}

#[test]
fn the_instructions_are_the_python_clients_byte_for_byte() {
    let f = fixture();
    let (funder, tok, mint, relayer) = (key(&f["funder"]), key(&f["funder_token"]), key(&f["mint"]), key(&f["relayer"]));
    let fund = fund_of(&f);
    let terms = f["terms"].as_str().unwrap().as_bytes();
    same(&fund_order_wallet(&ID, &funder, &tok, &mint, &TOKEN, &fund, terms), named(&f, "fund_order_wallet"));
    let salt: [u8; 32] = unhex(&f["salt"]).try_into().unwrap();
    let private = FundOrder { repo_id: 0, issue: 0, mode: TESTS, seq: 0,
                              opts: Opts { flags: F_PRIVATE, judge_repo_id: 5150, salted: true, ..Opts::default() },
                              private_scope: Some(private_scope(&salt, fund.repo_id, fund.issue)), ..fund };
    same(&fund_order_wallet(&ID, &funder, &tok, &mint, &TOKEN, &private, &terms_hash(terms)), named(&f, "fund_order_wallet_private"));
    let at = key(&f["order"]["address"]);
    let o = Order::parse(&unhex(&f["order"]["data"])).unwrap();
    same(&top_up(&ID, &funder, &at, &o, 5_000_000, None), named(&f, "top_up"));
    same(&top_up(&ID, &funder, &at, &o, 1, Some(&relayer)), named(&f, "top_up_from"));
    same(&refund_order(&ID, &relayer, &at, &o, None), named(&f, "refund_order"));
    same(&refund_order(&ID, &relayer, &at, &o, Some(&tok)), named(&f, "refund_order_to"));
}

#[test]
fn an_order_knos_pay_wrote_reads_as_the_python_client_reads_it() {
    let f = fixture();
    let (at, owner, data, w) = (key(&f["order"]["address"]), key(&f["order"]["owner"]), unhex(&f["order"]["data"]), &f["order"]["fields"]);
    let o = Order::read(&at, &owner, &data, &ID).unwrap();
    let state = match o.state { OPEN => "open", HELD => "held", WARRANTY => "warranty", _ => "?" };
    assert_eq!((state, o.mode as u64, o.from_balance, o.flags as u64, o.decimals as u64, o.reserve_days as u64),
               (w["state"].as_str().unwrap(), n(&w["mode"]), w["from_balance"].as_bool().unwrap(), n(&w["flags"]), n(&w["decimals"]), n(&w["reserve_days"])));
    assert_eq!((o.repo_id, o.issue, o.seq as u64, o.holdback_bps as u64, o.kill_bps as u64, o.amount, o.fee, o.rate, o.paid),
               (n(&w["repo_id"]), n(&w["issue"]), n(&w["seq"]), n(&w["holdback_bps"]), n(&w["kill_bps"]), n(&w["amount"]), n(&w["fee"]), n(&w["rate"]), n(&w["paid"])));
    assert_eq!((o.deadline, o.not_before, o.hold_until, o.warranty_s, o.reserved_until, o.cancel_at),
               (w["deadline"].as_i64().unwrap(), w["not_before"].as_i64().unwrap(), w["hold_until"].as_i64().unwrap(), w["warranty_s"].as_i64().unwrap(),
                w["reserved_until"].as_i64().unwrap(), w["cancel_at"].as_i64().unwrap()));
    assert_eq!((o.reserved_by, o.payee_id, o.funder_id, o.owner_id, o.arbiter_id, o.judge_repo_id, o.fee_bps as u64),
               (n(&w["reserved_by"]), n(&w["payee_id"]), n(&w["funder_id"]), n(&w["owner_id"]), n(&w["arbiter_id"]), n(&w["judge_repo_id"]), n(&w["fee_bps"])));
    assert_eq!((o.source, o.refund_to, o.rent_to, o.mint), (key(&w["source"]), key(&w["refund_to"]), key(&w["rent_to"]), key(&w["mint"])));
    assert_eq!((o.inc, o.grace), (n(&w["inc"]), w["grace"].as_bool().unwrap()));
    assert_eq!((o.scope.to_vec(), o.terms.to_vec(), o.wf_repo.to_vec()), (unhex(&w["scope"]), unhex(&w["terms"]), unhex(&w["wf_repo_hash"])));
    assert_eq!(core::str::from_utf8(&o.wf_sha).unwrap(), w["wf_sha"].as_str().unwrap());
    // what the funder asked for is what the order says, and the fee is the one this crate computes
    let fund = fund_of(&f);
    assert_eq!((o.amount, o.fee, o.deadline, o.address(&ID), o.token_program()),
               (fund.amount, order_fee(fund.amount, FEE_BPS, 6), f["now"].as_i64().unwrap() + fund.work_s, at, TOKEN));
    assert!(o.is(F_NEUTRAL) && !o.is(F_PRIVATE) && !o.refundable(o.deadline) && o.refundable(o.deadline + 1));
    // nothing but an order of this program at its own address reads as one
    assert!(Order::read(&at, &TOKEN, &data, &ID).is_none() && Order::read(&owner, &owner, &data, &ID).is_none());
    assert!(Order::read(&at, &owner, &data[..511], &ID).is_none());
    let mut other = data.clone();
    other[0] = 1;
    assert!(Order::read(&at, &owner, &other, &ID).is_none());
    other[0] = 2; other[56] ^= 1;                               // another seq: another address
    assert!(Order::read(&at, &owner, &other, &ID).is_none());
}
