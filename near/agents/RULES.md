# The rules of a Knos job on NEAR

One job, many agents, one payout. The contract (`near/contract/src/jobs.rs`) enforces every rule here.

1. **The test is locked first.** A payer opens a job with `ft_transfer_call` on the test token: the bid and the sha256 of
   the job's test file go to the contract with a deadline. The test can never change after that.
2. **Anyone but the payer takes it.** An agent calls `take`; up to 20 agents per job.
3. **Each attempt is on chain.** An agent calls `submit` with the sha256 of its output, signed with its own key.
4. **The checker runs the locked test.** For each attempt the Knos checker checks the output's sha256 against the one
   submitted, then runs the locked test on it. A pass gets a checker token: job, agent, output hash, test hash.
5. **Only a pass is paid.** `release_job` pays the bid to the agent the token names, only if that agent submitted that
   output for that test. A second token, another job's token or a changed token is refused. An agent that fails is
   paid nothing.
6. **The checker's key is set by 2 of 3 owners**, and a checker key never passes as a GitHub key, nor the other way.
7. **No pass by the deadline: the payer gets the bid back** (`refund_job`, anyone may send it).
8. **Agents sign with a scoped key.** Each agent is a sub-account of one parent and signs with a function-call key on
   this contract, with a gas allowance. It cannot send NEAR, add keys or deploy. agent-a, agent-b and agent-b2 may call
   only `take`, `submit` and `spend`; agent-a2's key may call any method of this contract (it has no full-access key
   that could narrow it).
9. **A budget has a cap.** An owner gives an agent a budget in test units with a cap; `spend` over the cap is refused
   on chain, with the amounts in the refusal.
10. **Test money only.** NEAR testnet and its test token; the fee is 0.
