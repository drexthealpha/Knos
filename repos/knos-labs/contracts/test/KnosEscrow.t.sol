// SPDX-License-Identifier: MIT
// The live Tempo run (every attack x10, reject, silent buyer, no delivery), ported to Foundry, plus the mainnet
// guard rails (cap, pause), the 0.3.4 additions (paid on proof, minimum job, fee floor), and a conservation fuzz
// (1,000 runs by default; 10,000 under FOUNDRY_PROFILE=nightly) that also drains every job and checks nothing stays
// stuck and nothing is paid twice.
pragma solidity ^0.8.26;

import {KnosEscrow, IERC20} from "../KnosEscrow.sol";

contract Token is IERC20 {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    function mint(address to, uint256 v) external { balanceOf[to] += v; }
    function approve(address s, uint256 v) external returns (bool) { allowance[msg.sender][s] = v; return true; }
    function transfer(address to, uint256 v) external returns (bool) {
        require(balanceOf[msg.sender] >= v, "bal"); balanceOf[msg.sender] -= v; balanceOf[to] += v; return true;
    }
    function transferFrom(address f, address to, uint256 v) external returns (bool) {
        require(balanceOf[f] >= v && allowance[f][msg.sender] >= v, "allow");
        allowance[f][msg.sender] -= v; balanceOf[f] -= v; balanceOf[to] += v; return true;
    }
}

interface Vm { function prank(address) external; function warp(uint256) external; function expectRevert() external; }

contract KnosEscrowTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    Token t; KnosEscrow e;
    address buyer = address(0xB0B); address worker = address(0xA1); address rival = address(0xA2);
    address attacker = address(0xBAD); address fee = address(0xFEE); address guardian = address(0x6A);
    address verifier = address(0x7E);
    uint128 constant P = 5_000_000;
    uint128 constant MIN = 1_000_000;
    uint128 constant MINFEE = 50_000;

    function setUp() public {
        t = new Token(); e = new KnosEscrow(IERC20(address(t)), fee, 500, MINFEE, MIN, 40, guardian, 0);
        t.mint(buyer, 1e15); vm.prank(buyer); t.approve(address(e), type(uint256).max);
    }
    function _post(bytes32 id) internal { vm.prank(buyer); e.post(id, P, 600); }
    function _ready(bytes32 id) internal { _post(id); vm.prank(worker); e.claim(id); vm.prank(worker); e.deliver(id, bytes32("r")); }
    function _readyV(bytes32 id) internal {
        vm.prank(buyer); e.postWithVerifier(id, P, 600, verifier);
        vm.prank(worker); e.claim(id); vm.prank(worker); e.deliver(id, bytes32("r"));
    }
    function _reverts(address who, bytes memory call) internal {
        vm.prank(who); (bool ok,) = address(e).call(call); require(!ok, "attack succeeded");
    }
    function _state(bytes32 id) internal view returns (KnosEscrow.S s) { (,,,, s,,,) = e.jobs(id); }

    function test_full_jobs_pay_95_and_5() public {
        for (uint256 i; i < 10; i++) { bytes32 id = keccak256(abi.encode(i)); _ready(id); vm.prank(buyer); e.accept(id); }
        require(t.balanceOf(worker) == 10 * uint256(P) * 95 / 100 && t.balanceOf(fee) == 10 * uint256(P) * 5 / 100, "split");
        require(t.balanceOf(address(e)) == 0, "stuck");
    }
    function test_attacks_are_refused() public {
        for (uint256 i; i < 10; i++) {
            bytes32 id = keccak256(abi.encode("a", i)); _post(id); vm.prank(worker); e.claim(id);
            _reverts(rival, abi.encodeCall(e.claim, (id)));                       // second claim
            _reverts(attacker, abi.encodeCall(e.deliver, (id, bytes32("x"))));    // delivery by a non-worker
            vm.prank(worker); e.deliver(id, bytes32("r"));
            _reverts(worker, abi.encodeCall(e.accept, (id)));                     // accept by the worker
            _reverts(attacker, abi.encodeCall(e.accept, (id)));                   // accept by an outsider
            _reverts(attacker, abi.encodeCall(e.release, (id)));                  // early release
            _reverts(worker, abi.encodeWithSignature("reject(bytes32)", id));     // reject by the worker
            _reverts(attacker, abi.encodeCall(e.verifyRelease, (id, bytes32("r"), bytes32("p")))); // no verifier named
            vm.prank(buyer); e.accept(id);
            _reverts(buyer, abi.encodeCall(e.accept, (id)));                      // double accept
            _reverts(buyer, abi.encodeCall(e.post, (id, P, 600)));                // reposting a job id
        }
    }
    function test_reject_silent_buyer_and_no_delivery() public {
        bytes32 a = "reject"; uint256 b0 = t.balanceOf(buyer); _ready(a); vm.prank(buyer); e.reject(a);
        require(t.balanceOf(buyer) == b0, "refund");
        bytes32 s = "silent"; _ready(s); _reverts(worker, abi.encodeCall(e.release, (s)));
        vm.warp(block.timestamp + 41); vm.prank(worker); e.release(s);
        bytes32 n = "nodeliver"; _post(n); _reverts(buyer, abi.encodeCall(e.refund, (n)));
        vm.warp(block.timestamp + 601); _reverts(rival, abi.encodeCall(e.claim, (n))); vm.prank(buyer); e.refund(n);
        require(t.balanceOf(address(e)) == 0, "stuck");
    }
    function test_mainnet_guard_rails() public {
        KnosEscrow m = new KnosEscrow(IERC20(address(t)), fee, 500, MINFEE, MIN, 40, guardian, 500e6);
        vm.prank(buyer); t.approve(address(m), type(uint256).max);
        vm.prank(buyer); (bool ok,) = address(m).call(abi.encodeCall(m.post, (bytes32("big"), 501e6, 600))); require(!ok, "cap");
        vm.prank(buyer); m.post(bytes32("ok"), 500e6, 600);
        vm.prank(buyer); m.postWithVerifier(bytes32("okv"), 2e6, 600, verifier);
        vm.prank(attacker); (ok,) = address(m).call(abi.encodeCall(m.setPaused, (true))); require(!ok, "only guardian");
        vm.prank(guardian); m.setPaused(true);
        vm.prank(buyer); (ok,) = address(m).call(abi.encodeCall(m.post, (bytes32("p"), 1e6, 600))); require(!ok, "paused");
        vm.prank(buyer); (ok,) = address(m).call(abi.encodeCall(m.postWithVerifier, (bytes32("p"), 1e6, 600, verifier)));
        require(!ok, "paused");
        vm.prank(worker); m.claim(bytes32("ok")); vm.prank(worker); m.deliver(bytes32("ok"), bytes32("r"));
        vm.prank(buyer); m.accept(bytes32("ok"));   // a pause never traps a job that is under way
        vm.prank(worker); m.claim(bytes32("okv")); vm.prank(worker); m.deliver(bytes32("okv"), bytes32("r"));
        vm.prank(verifier); m.verifyRelease(bytes32("okv"), bytes32("r"), bytes32("p"));   // nor a proven one
        vm.prank(guardian); (ok,) = address(m).call(abi.encodeCall(m.lowerCap, (600e6))); require(!ok, "cap only goes down");
        vm.prank(guardian); (ok,) = address(m).call(abi.encodeCall(m.lowerCap, (MIN - 1))); require(!ok, "not under the minimum");
        vm.prank(attacker); (ok,) = address(m).call(abi.encodeCall(m.lowerCap, (10e6))); require(!ok, "only guardian");
        vm.prank(guardian); m.lowerCap(10e6);
        vm.prank(guardian); m.setPaused(false);
        vm.prank(buyer); (ok,) = address(m).call(abi.encodeCall(m.post, (bytes32("p2"), 10e6 + 1, 600))); require(!ok, "cap enforced");
        vm.prank(buyer); m.post(bytes32("p2"), 10e6, 600);
        require(t.balanceOf(address(m)) == 10e6, "only the open job is held");
    }
    function test_paid_on_proof() public {
        bytes32 id = "proof"; _readyV(id);
        _reverts(buyer, abi.encodeCall(e.verifyRelease, (id, bytes32("r"), bytes32("p"))));     // not the verifier
        _reverts(worker, abi.encodeCall(e.verifyRelease, (id, bytes32("r"), bytes32("p"))));
        _reverts(attacker, abi.encodeCall(e.verifyRelease, (id, bytes32("r"), bytes32("p"))));
        vm.prank(verifier); (bool ok, bytes memory why) = address(e).call(abi.encodeCall(e.verifyRelease, (id, bytes32("x"), bytes32("p"))));
        require(!ok && keccak256(why) == keccak256(abi.encodeWithSignature("Error(string)", "verifier releases unproven work")),
                "verifier releases unproven work: refused");
        vm.prank(verifier); e.verifyRelease(id, bytes32("r"), bytes32("root"));
        (,,,,,,, bytes32 proof) = e.jobs(id);
        require(proof == bytes32("root") && _state(id) == KnosEscrow.S.Released, "proof stored, released");
        require(t.balanceOf(worker) == uint256(P) * 95 / 100 && t.balanceOf(fee) == uint256(P) * 5 / 100, "paid like accept");
        _reverts(verifier, abi.encodeCall(e.verifyRelease, (id, bytes32("r"), bytes32("root"))));   // double release
        _reverts(buyer, abi.encodeCall(e.accept, (id)));
        // before delivery
        bytes32 early = "early"; vm.prank(buyer); e.postWithVerifier(early, P, 600, verifier);
        _reverts(verifier, abi.encodeCall(e.verifyRelease, (early, bytes32(0), bytes32("p"))));
        vm.prank(worker); e.claim(early);
        _reverts(verifier, abi.encodeCall(e.verifyRelease, (early, bytes32(0), bytes32("p"))));
        // a worker that is the verifier cannot release its own work
        bytes32 self = "self"; vm.prank(buyer); e.postWithVerifier(self, P, 600, worker);
        vm.prank(worker); e.claim(self); vm.prank(worker); e.deliver(self, bytes32("r"));
        _reverts(worker, abi.encodeCall(e.verifyRelease, (self, bytes32("r"), bytes32("p"))));
        // a silent verifier: buyer accept, reject, and release after the window all still work
        bytes32 a = "va"; _readyV(a); vm.prank(buyer); e.accept(a);
        bytes32 r = "vr"; _readyV(r); vm.prank(buyer); e.reject(r);
        bytes32 s = "vs"; _readyV(s); vm.warp(block.timestamp + 41); vm.prank(rival); e.release(s);
    }
    function test_minimum_and_fee_floor() public {
        _reverts(buyer, abi.encodeCall(e.post, (bytes32("small"), MIN - 1, 600)));             // below the minimum
        vm.prank(buyer); e.post(bytes32("min"), MIN, 600);
        require(e.fee(MIN) == 50_000 && e.fee(3e6) == 150_000, "5% at and above the minimum");
        KnosEscrow lo = new KnosEscrow(IERC20(address(t)), fee, 500, MINFEE, 100_000, 40, guardian, 0);
        vm.prank(buyer); t.approve(address(lo), type(uint256).max);
        vm.prank(buyer); lo.post(bytes32("half"), 500_000, 600);
        vm.prank(worker); lo.claim(bytes32("half")); vm.prank(worker); lo.deliver(bytes32("half"), bytes32("r"));
        uint256 f0 = t.balanceOf(fee);
        vm.prank(buyer); lo.accept(bytes32("half"));
        require(t.balanceOf(fee) - f0 == 50_000, "fee floor applied (5% would be 25,000)");
        (bool ok,) = address(this).call(abi.encodeWithSignature("deployBad()")); require(!ok, "minFee above minAmount refused");
    }
    function deployBad() external { new KnosEscrow(IERC20(address(t)), fee, 500, 2e6, 1e6, 40, guardian, 0); }

    // Conservation, no double payout, nothing stuck: random actions by four funded actors on six job ids, then every
    // job drained to a terminal state.
    function testFuzz_conservation(uint8[24] calldata acts, uint8[24] calldata who, uint8[24] calldata ids,
                                   uint8[24] calldata amts) public {
        address[4] memory ppl = [buyer, worker, rival, attacker];
        for (uint256 k = 1; k < 4; k++) { t.mint(ppl[k], 1e12); vm.prank(ppl[k]); t.approve(address(e), type(uint256).max); }
        uint256 total = _sum(ppl);
        for (uint256 k; k < 24; k++) {
            _step(ppl, acts[k] % 10, who[k] % 4, bytes32(uint256(ids[k] % 6)), amts[k]);
            require(_sum(ppl) == total, "tokens created or destroyed");
        }
        vm.warp(block.timestamp + 1000);
        uint256 fees;
        for (uint256 i; i < 6; i++) fees += _drain(bytes32(i));
        require(t.balanceOf(address(e)) == 0, "funds stuck in escrow");
        require(t.balanceOf(fee) == fees, "a job paid twice, or a fee went missing");
        require(_sum(ppl) == total, "tokens created or destroyed");
    }
    function _step(address[4] memory ppl, uint8 a, uint8 wi, bytes32 id, uint8 x) internal {
        uint128 amt = MIN + uint128(x) * 10_000;
        vm.prank(ppl[wi]);
        if (a == 0) address(e).call(abi.encodeCall(e.post, (id, amt, 30)));
        else if (a == 1) address(e).call(abi.encodeCall(e.postWithVerifier, (id, amt, 30, ppl[(wi + 1) % 4])));
        else if (a == 2) address(e).call(abi.encodeCall(e.claim, (id)));
        else if (a == 3) address(e).call(abi.encodeCall(e.deliver, (id, bytes32("r"))));
        else if (a == 4) address(e).call(abi.encodeCall(e.accept, (id)));
        else if (a == 5) address(e).call(abi.encodeCall(e.release, (id)));
        else if (a == 6) address(e).call(abi.encodeWithSignature("reject(bytes32)", id));
        else if (a == 7) address(e).call(abi.encodeCall(e.refund, (id)));
        else if (a == 8) address(e).call(abi.encodeCall(e.verifyRelease, (id, x % 2 == 0 ? bytes32("r") : bytes32("x"), bytes32("p"))));
        else vm.warp(block.timestamp + 35);
    }
    // Drive one job to a terminal state; return the fee it paid (0 unless released).
    function _drain(bytes32 id) internal returns (uint256) {
        (address b,, uint128 amount,, KnosEscrow.S s,,,) = e.jobs(id);
        if (s == KnosEscrow.S.Delivered) { e.release(id); return e.fee(amount); }
        if (s == KnosEscrow.S.Open || s == KnosEscrow.S.Claimed) { vm.prank(b); e.refund(id); return 0; }
        return s == KnosEscrow.S.Released ? e.fee(amount) : 0;
    }
    // ---- ERC-8183 (0.3.6) ----
    // createJob (client = buyer, provider = worker, evaluator = verifier) -> setBudget -> fund -> submit.
    function _acp(address evaluator) internal returns (uint256 id) {
        vm.prank(buyer); id = e.createJob(worker, evaluator, block.timestamp + 600, "job", address(0));
        vm.prank(worker); e.setBudget(id, P, "");
        vm.prank(buyer); e.fund(id, "");
        vm.prank(worker); e.submit(id, bytes32("deliv"), "");
    }
    function _status(uint256 id) internal view returns (KnosEscrow.JobStatus) { return e.getJob(id).status; }
    function _acpReject(uint256 id) internal pure returns (bytes memory) {
        return abi.encodeWithSignature("reject(uint256,bytes32,bytes)", id, bytes32("no"), bytes(""));
    }

    function test_erc8183_evaluator_only_complete() public {
        uint256 id = _acp(verifier);
        _reverts(buyer, abi.encodeCall(e.complete, (id, bytes32("ok"), "")));      // client cannot complete
        _reverts(worker, abi.encodeCall(e.complete, (id, bytes32("ok"), "")));     // provider cannot complete
        _reverts(attacker, abi.encodeCall(e.complete, (id, bytes32("ok"), "")));
        vm.prank(verifier); e.complete(id, bytes32("proof-root"), "");
        require(_status(id) == KnosEscrow.JobStatus.Completed, "completed");
        require(t.balanceOf(worker) == uint256(P) * 95 / 100 && t.balanceOf(fee) == uint256(P) * 5 / 100, "95/5");
        _reverts(verifier, abi.encodeCall(e.complete, (id, bytes32("ok"), "")));   // double complete
        _reverts(verifier, _acpReject(id));                                        // reject after complete
        vm.warp(block.timestamp + 601);
        _reverts(buyer, abi.encodeCall(e.claimRefund, (id)));                      // refund after complete
        require(t.balanceOf(address(e)) == 0, "stuck");
    }
    function test_erc8183_evaluator_only_reject_client_cannot() public {
        uint256 b0 = t.balanceOf(buyer);
        uint256 id = _acp(verifier);
        _reverts(buyer, _acpReject(id));                    // client cannot reject once an evaluator holds it
        _reverts(worker, _acpReject(id));
        _reverts(attacker, _acpReject(id));
        vm.prank(verifier); e.reject(id, bytes32("bad"), "");
        require(_status(id) == KnosEscrow.JobStatus.Rejected && t.balanceOf(buyer) == b0, "full refund");
        require(t.balanceOf(fee) == 0, "no fee on reject");
        // the evaluator may also reject a funded job before submission; the client cannot
        vm.prank(buyer); uint256 f = e.createJob(worker, verifier, block.timestamp + 600, "f", address(0));
        vm.prank(worker); e.setBudget(f, P, ""); vm.prank(buyer); e.fund(f, "");
        _reverts(buyer, _acpReject(f));
        vm.prank(verifier); e.reject(f, bytes32("x"), "");
        // while Open (nothing escrowed) the client may withdraw the job
        vm.prank(buyer); uint256 o = e.createJob(worker, verifier, block.timestamp + 600, "o", address(0));
        _reverts(verifier, _acpReject(o));
        vm.prank(buyer); e.reject(o, bytes32("cancel"), "");
        require(_status(o) == KnosEscrow.JobStatus.Rejected && t.balanceOf(buyer) == b0, "nothing moved");
    }
    function test_erc8183_provider_is_never_evaluator() public {
        _reverts(buyer, abi.encodeCall(e.createJob, (worker, worker, block.timestamp + 600, "s", address(0))));
        _reverts(buyer, abi.encodeCall(e.createJob, (worker, address(0), block.timestamp + 600, "z", address(0))));
        vm.prank(buyer); uint256 id = e.createJob(address(0), verifier, block.timestamp + 600, "later", address(0));
        _reverts(buyer, abi.encodeCall(e.setProvider, (id, verifier)));            // evaluator as provider, later
        _reverts(attacker, abi.encodeCall(e.setProvider, (id, worker)));           // only the client sets it
        _reverts(buyer, abi.encodeCall(e.fund, (id, "")));                         // no provider yet
        vm.prank(buyer); e.setProvider(id, worker);
        _reverts(buyer, abi.encodeCall(e.setProvider, (id, rival)));               // set once
        // other ERC-8183 rules: 5-minute expiry floor, no unlisted hook, budget by provider, minimum job
        _reverts(buyer, abi.encodeCall(e.createJob, (worker, verifier, block.timestamp + 300, "e", address(0))));
        _reverts(buyer, abi.encodeCall(e.createJob, (worker, verifier, block.timestamp + 600, "h", address(0xF00))));
        _reverts(buyer, abi.encodeCall(e.setBudget, (id, P, "")));
        vm.prank(worker); e.setBudget(id, MIN - 1, "");
        _reverts(buyer, abi.encodeCall(e.fund, (id, "")));                         // below the minimum job
        vm.prank(worker); e.setBudget(id, P, "");
        _reverts(worker, abi.encodeCall(e.submit, (id, bytes32("d"), "")));        // not funded
        vm.prank(buyer); e.fund(id, "");
        _reverts(worker, abi.encodeCall(e.setBudget, (id, 2 * P, "")));            // budget fixed once funded
        _reverts(rival, abi.encodeCall(e.submit, (id, bytes32("d"), "")));         // only the provider submits
        vm.prank(guardian); e.setPaused(true);
        vm.prank(worker); e.submit(id, bytes32("d"), "");                          // a pause never traps a funded job
        vm.prank(verifier); e.complete(id, bytes32("ok"), "");
    }
    function test_erc8183_claimRefund_after_expiry_cannot_be_blocked() public {
        uint256 b0 = t.balanceOf(buyer);
        uint256 s = _acp(verifier);                                                // submitted, evaluator silent
        vm.prank(buyer); uint256 f = e.createJob(worker, verifier, block.timestamp + 600, "f", address(0));
        vm.prank(worker); e.setBudget(f, P, ""); vm.prank(buyer); e.fund(f, "");   // funded, provider silent
        _reverts(attacker, abi.encodeCall(e.claimRefund, (s)));                   // not before expiry
        _reverts(buyer, abi.encodeCall(e.claimRefund, (f)));
        vm.warp(block.timestamp + 600);
        _reverts(worker, abi.encodeCall(e.submit, (f, bytes32("late"), "")));      // too late to submit
        vm.prank(guardian); e.setPaused(true);                                     // even paused
        vm.prank(attacker); e.claimRefund(s);                                      // anyone, to the client
        vm.prank(rival); e.claimRefund(f);
        require(_status(s) == KnosEscrow.JobStatus.Expired && _status(f) == KnosEscrow.JobStatus.Expired, "expired");
        require(t.balanceOf(buyer) == b0 && t.balanceOf(fee) == 0 && t.balanceOf(address(e)) == 0, "refunded, no fee");
        _reverts(buyer, abi.encodeCall(e.claimRefund, (s)));                       // only once
        _reverts(verifier, abi.encodeCall(e.complete, (s, bytes32("ok"), "")));
    }
    function test_erc8183_fee_only_on_complete() public {
        uint256 c = _acp(verifier); vm.prank(verifier); e.complete(c, bytes32("ok"), "");
        uint256 r = _acp(verifier); vm.prank(verifier); e.reject(r, bytes32("no"), "");
        uint256 x = _acp(verifier); vm.warp(block.timestamp + 601); e.claimRefund(x);
        require(t.balanceOf(fee) == e.fee(P) && t.balanceOf(worker) == P - e.fee(P), "one fee, from the completed job");
        require(t.balanceOf(address(e)) == 0, "stuck");
    }
    function testFuzz_erc8183_conservation(uint8[16] calldata acts, uint8[16] calldata who) public {
        address[4] memory ppl = [buyer, worker, verifier, attacker];
        for (uint256 k = 1; k < 4; k++) { t.mint(ppl[k], 1e12); vm.prank(ppl[k]); t.approve(address(e), type(uint256).max); }
        uint256 total = _sum(ppl);
        for (uint256 k; k < 16; k++) {
            uint256 id = 1 + (who[k] >> 2) % 3; uint8 a = acts[k] % 9; address w = ppl[who[k] % 4];
            vm.prank(w);
            if (a == 0) address(e).call(abi.encodeCall(e.createJob, (worker, verifier, block.timestamp + 400, "j", address(0))));
            else if (a == 1) address(e).call(abi.encodeCall(e.setBudget, (id, MIN + acts[k], "")));
            else if (a == 2) address(e).call(abi.encodeCall(e.fund, (id, "")));
            else if (a == 3) address(e).call(abi.encodeCall(e.submit, (id, bytes32("d"), "")));
            else if (a == 4) address(e).call(abi.encodeCall(e.complete, (id, bytes32("ok"), "")));
            else if (a == 5) address(e).call(_acpReject(id));
            else if (a == 6) address(e).call(abi.encodeCall(e.claimRefund, (id)));
            else vm.warp(block.timestamp + 200);
            require(_sum(ppl) == total, "tokens created or destroyed");
        }
        vm.warp(block.timestamp + 1000);
        for (uint256 i = 1; i <= e.jobCount(); i++) {
            KnosEscrow.JobStatus s = _status(i);
            if (s == KnosEscrow.JobStatus.Funded || s == KnosEscrow.JobStatus.Submitted) e.claimRefund(i);
        }
        require(t.balanceOf(address(e)) == 0, "funds stuck in escrow");
    }

    function _sum(address[4] memory ppl) internal view returns (uint256 s) {
        for (uint256 k; k < 4; k++) s += t.balanceOf(ppl[k]);
        s += t.balanceOf(fee) + t.balanceOf(address(e));
    }
}
