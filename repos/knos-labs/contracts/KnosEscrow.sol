// SPDX-License-Identifier: MIT
// Knos: pay-on-acceptance (or pay-on-proof) escrow for AI agent jobs on Tempo (EVM; TIP-20 tokens have the ERC-20
// interface). Same state machine as the Solana program (programs/knos_escrow):
//   post -> claim -> deliver -> accept | verifyRelease | reject (inside the review window) | release (anyone, after
//   it) | refund.
// Non-custodial: no one, including the guardian, can move a job's money anywhere but to its buyer or its worker
// (and the fee address, on release). The guardian can only pause NEW posts and lower the per-job cap.
// 0.3.4: a job may name a verifier who releases it on proof (the exact committed result hash, plus a proof root);
// a minimum job and a minimum fee (fee = max(feeBps of the price, minFee)).
// 0.3.6: the ERC-8183 job interface (createJob ... complete / reject / claimRefund) beside it; see docs/ERC8183.md.
pragma solidity ^0.8.26;

interface IERC20 {
    function transferFrom(address from, address to, uint256 v) external returns (bool);
    function transfer(address to, uint256 v) external returns (bool);
}

contract KnosEscrow {
    enum S { None, Open, Claimed, Delivered, Released, Refunded }
    struct Job {
        address buyer; address worker; uint128 amount; uint64 deadline; S state; bytes32 result;
        address verifier;   // may release on proof; zero = none
        bytes32 proof;      // the proof root the verifier released with
    }

    IERC20 public immutable token;
    address public immutable feeTo;
    uint16 public immutable feeBps;
    uint128 public immutable minFee;    // fee floor, in token units
    uint128 public immutable minAmount; // the minimum job, in token units
    uint64 public immutable review;     // seconds the buyer has to accept or reject a delivery
    address public immutable guardian;  // may pause new posts and lower the cap; never touches funds
    uint128 public maxAmount;           // per-job cap (0 = none). Mainnet starts capped until an external audit.
    bool public paused;                 // stops new posts only: every existing job can still finish or refund
    mapping(bytes32 => Job) public jobs;

    event Posted(bytes32 indexed id, address buyer, uint256 amount);
    event Claimed(bytes32 indexed id, address worker);
    event Delivered(bytes32 indexed id, bytes32 result);
    event Released(bytes32 indexed id, uint256 toWorker, uint256 fee);
    event Proven(bytes32 indexed id, address verifier, bytes32 proofRoot);
    event Refunded(bytes32 indexed id);
    event Paused(bool on);
    event Cap(uint128 maxAmount);

    constructor(IERC20 t, address f, uint16 bps, uint128 minFee_, uint128 minAmount_, uint64 reviewSeconds, address g,
                uint128 cap) {
        require(bps <= 2000, "fee too high");
        require(minAmount_ > 0 && minFee_ <= minAmount_ && (cap == 0 || cap >= minAmount_), "limits");
        token = t; feeTo = f; feeBps = bps; minFee = minFee_; minAmount = minAmount_; review = reviewSeconds;
        guardian = g; maxAmount = cap;
    }

    function setPaused(bool on) external { require(msg.sender == guardian, "guardian"); paused = on; emit Paused(on); }
    // The cap can only go down (or stay), never under the minimum job: raising it needs a new deployment, after an audit.
    function lowerCap(uint128 cap) external {
        require(msg.sender == guardian && cap >= minAmount && (maxAmount == 0 || cap <= maxAmount), "cap");
        maxAmount = cap; emit Cap(cap);
    }

    function fee(uint256 amount) public view returns (uint256 f) {
        f = amount * feeBps / 10000;
        if (amount >= minAmount && f < minFee) f = minFee;
        if (f > amount) f = amount;
    }

    // Buyer: one call locks the price. `work` = seconds a worker has to deliver before the buyer can take it back.
    function post(bytes32 id, uint128 amount, uint64 work) external { _post(id, amount, work, address(0)); }
    // The same, naming a verifier who may release the delivered work on proof (no buyer step).
    function postWithVerifier(bytes32 id, uint128 amount, uint64 work, address verifier) external {
        _post(id, amount, work, verifier);
    }
    function _post(bytes32 id, uint128 amount, uint64 work, address verifier) internal {
        require(!paused, "paused");
        require(amount >= minAmount, "below minimum");
        require(work > 0, "terms");
        require(maxAmount == 0 || amount <= maxAmount, "over cap");
        require(jobs[id].state == S.None, "exists");
        jobs[id] = Job(msg.sender, address(0), amount, uint64(block.timestamp) + work, S.Open, bytes32(0), verifier,
                       bytes32(0));
        require(token.transferFrom(msg.sender, address(this), amount), "pay");
        emit Posted(id, msg.sender, amount);
    }
    // Exactly one worker.
    function claim(bytes32 id) external {
        Job storage j = jobs[id];
        require(j.state == S.Open && block.timestamp <= j.deadline, "not open");
        j.worker = msg.sender; j.state = S.Claimed;
        emit Claimed(id, msg.sender);
    }
    function deliver(bytes32 id, bytes32 result) external {
        Job storage j = jobs[id];
        require(j.state == S.Claimed && msg.sender == j.worker, "not worker");
        j.result = result; j.state = S.Delivered; j.deadline = uint64(block.timestamp) + review;
        emit Delivered(id, result);
    }
    // Buyer accepts: worker paid at once.
    function accept(bytes32 id) external {
        Job storage j = jobs[id];
        require(j.state == S.Delivered && msg.sender == j.buyer, "not buyer");
        _release(id, j);
    }
    // Paid on proof: the job's verifier releases delivered work, naming the exact result the worker committed.
    function verifyRelease(bytes32 id, bytes32 resultHash, bytes32 proofRoot) external {
        Job storage j = jobs[id];
        require(j.verifier != address(0) && msg.sender == j.verifier, "not verifier");
        require(msg.sender != j.worker, "worker cannot verify own work");
        require(j.state == S.Delivered, "not delivered");
        require(resultHash == j.result, "verifier releases unproven work");
        j.proof = proofRoot;
        emit Proven(id, msg.sender, proofRoot);
        _release(id, j);
    }
    // Buyer rejects inside the review window: refund. (Rejection rates are public, so agents can avoid serial rejecters.)
    function reject(bytes32 id) external {
        Job storage j = jobs[id];
        require(j.state == S.Delivered && msg.sender == j.buyer && block.timestamp <= j.deadline, "no");
        j.state = S.Refunded;
        require(token.transfer(j.buyer, j.amount), "refund");
        emit Refunded(id);
    }
    // Buyer went silent past the review window: anyone can release to the worker.
    function release(bytes32 id) external {
        Job storage j = jobs[id];
        require(j.state == S.Delivered && block.timestamp > j.deadline, "in review");
        _release(id, j);
    }
    // Nobody delivered in time: buyer takes the money back.
    function refund(bytes32 id) external {
        Job storage j = jobs[id];
        require((j.state == S.Open || j.state == S.Claimed) && block.timestamp > j.deadline && msg.sender == j.buyer, "no");
        j.state = S.Refunded;
        require(token.transfer(j.buyer, j.amount), "refund");
        emit Refunded(id);
    }
    function _release(bytes32 id, Job storage j) internal {
        j.state = S.Released;
        uint256 f = fee(j.amount);
        require(token.transfer(j.worker, j.amount - f), "worker");
        if (f > 0) require(token.transfer(feeTo, f), "fee");
        emit Released(id, j.amount - f, f);
    }

    // ---------------------------------------------------------------------------------------------------------------
    // 0.3.6: ERC-8183 (Agentic Commerce), alongside the Knos jobs above. client = buyer, provider = worker,
    // evaluator = verifier. Knos verifier rule: the evaluator can never be the provider, and once a job is funded only
    // the evaluator (complete / reject) or expiry (claimRefund, by anyone) settles it: the client cannot reject it.
    // Same guard rails as post: a pause stops new funding, the minimum job and the cap apply. Fee only on Completed.
    // Hooks: none are whitelisted, so `hook` must be zero. claimRefund is never hookable.
    enum JobStatus { Open, Funded, Submitted, Completed, Rejected, Expired }
    struct AcpJob {
        uint256 id; address client; address provider; address evaluator; string description; uint256 budget;
        uint256 expiredAt; JobStatus status; address hook;
    }
    uint256 public jobCount;
    mapping(uint256 => AcpJob) internal acp;

    event JobCreated(uint256 indexed jobId, address indexed client, address indexed provider, address evaluator,
                     uint256 expiredAt, address hook);
    event ProviderSet(uint256 indexed jobId, address indexed provider);
    event BudgetSet(uint256 indexed jobId, uint256 amount);
    event JobFunded(uint256 indexed jobId, address indexed client, uint256 amount);
    event JobSubmitted(uint256 indexed jobId, address indexed provider, bytes32 deliverable);
    event JobCompleted(uint256 indexed jobId, address indexed evaluator, bytes32 reason);
    event JobRejected(uint256 indexed jobId, address indexed rejector, bytes32 reason);
    event JobExpired(uint256 indexed jobId);
    event PaymentReleased(uint256 indexed jobId, address indexed provider, uint256 amount);
    event Refunded(uint256 indexed jobId, address indexed client, uint256 amount);

    function getJob(uint256 jobId) external view returns (AcpJob memory) { return acp[jobId]; }

    function createJob(address provider, address evaluator, uint256 expiredAt, string calldata description,
                       address hook) external returns (uint256 jobId) {
        require(evaluator != address(0), "evaluator");
        require(evaluator != provider, "evaluator cannot be provider");
        require(expiredAt > block.timestamp + 5 minutes, "expiredAt");
        require(hook == address(0), "hook not whitelisted");
        jobId = ++jobCount;
        acp[jobId] = AcpJob(jobId, msg.sender, provider, evaluator, description, 0, expiredAt, JobStatus.Open, hook);
        emit JobCreated(jobId, msg.sender, provider, evaluator, expiredAt, hook);
    }
    function setProvider(uint256 jobId, address provider_) external {
        AcpJob storage j = acp[jobId];
        require(j.status == JobStatus.Open && j.client != address(0) && msg.sender == j.client, "not client");
        require(j.provider == address(0) && provider_ != address(0), "provider");
        require(provider_ != j.evaluator, "evaluator cannot be provider");
        j.provider = provider_;
        emit ProviderSet(jobId, provider_);
    }
    function setBudget(uint256 jobId, uint256 amount, bytes calldata) external {
        AcpJob storage j = acp[jobId];
        require(j.status == JobStatus.Open && j.provider != address(0) && msg.sender == j.provider, "not provider");
        j.budget = amount;
        emit BudgetSet(jobId, amount);
    }
    function fund(uint256 jobId, bytes calldata) external {
        AcpJob storage j = acp[jobId];
        require(j.status == JobStatus.Open && j.client != address(0) && msg.sender == j.client, "not client");
        require(j.provider != address(0), "no provider");
        require(!paused, "paused");
        require(block.timestamp < j.expiredAt, "expired");
        uint256 b = j.budget;
        require(b >= minAmount, "below minimum");
        require(maxAmount == 0 || b <= maxAmount, "over cap");
        j.status = JobStatus.Funded;
        require(token.transferFrom(msg.sender, address(this), b), "pay");
        emit JobFunded(jobId, msg.sender, b);
    }
    function submit(uint256 jobId, bytes32 deliverable, bytes calldata) external {
        AcpJob storage j = acp[jobId];
        require(j.status == JobStatus.Funded && msg.sender == j.provider, "not provider");
        require(block.timestamp < j.expiredAt, "expired");
        j.status = JobStatus.Submitted;
        emit JobSubmitted(jobId, msg.sender, deliverable);
    }
    // Evaluator only (never the provider): pays the provider, minus the platform fee.
    function complete(uint256 jobId, bytes32 reason, bytes calldata) external {
        AcpJob storage j = acp[jobId];
        require(j.status == JobStatus.Submitted && msg.sender == j.evaluator, "not evaluator");
        require(msg.sender != j.provider, "provider cannot evaluate own work");
        j.status = JobStatus.Completed;
        uint256 f = fee(j.budget);
        require(token.transfer(j.provider, j.budget - f), "provider");
        if (f > 0) require(token.transfer(feeTo, f), "fee");
        emit JobCompleted(jobId, msg.sender, reason);
        emit PaymentReleased(jobId, j.provider, j.budget - f);
    }
    // The client while Open (nothing escrowed); once funded, the evaluator only. Full refund, no fee.
    function reject(uint256 jobId, bytes32 reason, bytes calldata) external {
        AcpJob storage j = acp[jobId];
        JobStatus s = j.status;
        if (s == JobStatus.Open) require(j.client != address(0) && msg.sender == j.client, "not client");
        else require((s == JobStatus.Funded || s == JobStatus.Submitted) && msg.sender == j.evaluator, "not evaluator");
        j.status = JobStatus.Rejected;
        emit JobRejected(jobId, msg.sender, reason);
        if (s != JobStatus.Open) _acpRefund(jobId, j);
    }
    // After expiry anyone recovers a funded or submitted job for the client. Not hookable: nobody can block it.
    function claimRefund(uint256 jobId) external {
        AcpJob storage j = acp[jobId];
        require(j.status == JobStatus.Funded || j.status == JobStatus.Submitted, "not refundable");
        require(block.timestamp >= j.expiredAt, "not expired");
        j.status = JobStatus.Expired;
        emit JobExpired(jobId);
        _acpRefund(jobId, j);
    }
    function _acpRefund(uint256 jobId, AcpJob storage j) internal {
        require(token.transfer(j.client, j.budget), "refund");
        emit Refunded(jobId, j.client, j.budget);
    }
}
