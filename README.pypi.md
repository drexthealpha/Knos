<!-- Written by scripts/bump_version.py from README.md, with links pinned to the tag: edit README.md. -->
<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/drexthealpha/Knos/v0.4.1/web/brand/wordmark-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/drexthealpha/Knos/v0.4.1/web/brand/wordmark-light.svg">
    <img alt="Knos" src="https://raw.githubusercontent.com/drexthealpha/Knos/v0.4.1/web/brand/wordmark-light.svg" height="84">
  </picture>
</h1>

Knos checks whether a research paper's claim holds: two agents write code against a test that NEAR locks before they
start, and only the agent whose code passes is paid.

The problem: research takes about 17 years to reach people, because checking that a result really works is slow and
costly ([Morris, Wooding and Grant, 2011](https://doi.org/10.1258/jrsm.2011.110180)).

| You judge for | Read | Try it live |
|---|---|---|
| From NEAR HACKATHON | [Knos on NEAR](https://github.com/drexthealpha/Knos/blob/v0.4.1/README.md#from-near-hackathon) | https://drexthealpha.github.io/Knos/ |
| From the InterSystems contest | [Knos on IRIS](https://github.com/drexthealpha/Knos/blob/v0.4.1/README.md#from-the-intersystems-contest) | the IRIS production, on your machine |
| From Colosseum | [The ten-second check](https://github.com/drexthealpha/Knos/blob/v0.4.1/README.md#from-colosseum) | https://drexthealpha.github.io/Knos/check/ |

Test money only: test USDC on NEAR testnet and Solana devnet. No customers yet.

<!-- entry:near -->
## From NEAR HACKATHON

A buyer pastes a paper's link and orders a proof of its claim. NEAR locks the claim's test by its sha256 in a jobs
contract before any agent starts, refuses any agent step over its spending cap, and pays only the agent whose code
passes. The buyer gets a Yes or No, the code and a receipt on NEAR testnet.

Agent A's code is written by a private model on NEAR AI Cloud, its attestation checked; a second model call reviews it
and may only reject it.

### Judge it in 2 minutes

1. Open https://drexthealpha.github.io/Knos/ and press **Try: HyperLogLog** - see "Yes, the claim holds", the claim,
   its locked test with its sha256 and its last proof on NEAR.
2. Press **Prove it yourself**, then **Prove it with 10 test USDC** - see "1. The test is locked", "2. Two agents ran
   the paper's result against the locked test", "3. The spending cap blocked an over-budget step" with NEAR's refusal,
   then "4. Answer: Yes, the claim holds", in about 5 s when a job is ready and 1 to 2 min when one is not.
3. In step 2, see "Agent A's code was written by" with the model and its call id, or "Agent A's code: a fixed program"
   and why. Then see "Receipt for proof job-...": 9.00 test USDC to agent A and 1.00 to Knos in one transaction, linked
   on the NEAR explorer. Press **Prove the same claim again** - see "Free: Yes".
4. From a clone (`git clone https://github.com/drexthealpha/Knos && cd Knos`; on Windows, Git Bash with `py -3`):

   ```bash
   sha256sum near/agents/job/test_jump.py
   curl -s https://rpc.testnet.fastnear.com -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"query","params":{"request_type":"call_function","finality":"final","account_id":"jobs.knos-swarm-1105.testnet","method_name":"get_job","args_base64":"eyJpZCI6ImpvYi0xMTEyMDUzMjM5In0="}}' | python3 -c 'import json,sys; j=json.loads(bytes(json.load(sys.stdin)["result"]["result"])); print(j["criteria_hash"], j["state"])'
   d=$(mktemp -d) && cp near/agents/job/test_jump.py $d/ && cp near/agents/solutions/jump_a.py $d/solution.py && (cd $d && python3 test_jump.py)
   ```

   - see `ffa9d064744e7ea0cc326039f55a979a588e2c1cdb3f59368ff4a99c986057cb  near/agents/job/test_jump.py`, then
     `ffa9d064744e7ea0cc326039f55a979a588e2c1cdb3f59368ff4a99c986057cb Paid` (the hash NEAR locked for
     job-1112053239), then `Passed: 9.2% of 100,000 keys moved going from 10 to 11 buckets (the ideal: 9.1%), all to
     the new one, the fullest bucket 1.5% over the mean, nothing stored.`

Video, recorded from the live pages: [near/web/knos-near.mp4](https://github.com/drexthealpha/Knos/blob/v0.4.1/near/web/knos-near.mp4). An agent runs the same flow in
one call:

```bash
curl -X POST https://knos.onrender.com/api/near/claim/flow -H "Content-Type: application/json" -d '{"url": "https://doi.org/10.46298/dmtcs.3545", "amount": 10}'
```

It answers with `verdict`, `code`, `cap`, `paid`, `settled` and `receipt`.

### What NEAR does here

| NEAR feature | In Knos | Where |
|---|---|---|
| Contracts | the jobs contract locks each test's sha256 and pays the passing agent; the claim contract keeps each claim's record and its two markets; the 90/10 split is one transaction | `near/contract/`, `near/market/`; accounts in [docs/near.md](https://github.com/drexthealpha/Knos/blob/v0.4.1/docs/near.md) |
| Agent spending caps | each agent key can call only the jobs contract, and a step over its cap is refused on chain | the receipt's "spending cap" step |
| Private inference | NEAR AI Cloud writes and reviews agent A's code; its attestation and each answer's signature are verified before the page says "private" | `apps/wanted/knos_wanted/near_attest.py` |
| Chain Signatures | a NEAR account pays a Solana address on devnet | [docs/near.md](https://github.com/drexthealpha/Knos/blob/v0.4.1/docs/near.md) |

### The diff, disclosure and libraries

- **The diff.** The tag `pre-hackathon` (31 Oct 2026) is the commit before the first line of `near/`; the tag
  `hackathon-submission` is the submitted commit. Everything built in the window:
  https://github.com/drexthealpha/Knos/compare/pre-hackathon...hackathon-submission. Only that NEAR work is the entry.
- **Built before, on another chain.** Knos's pull request check and its programs on Solana devnet were built before the
  window for Colosseum (tag v0.3.28). They are not part of this entry.
- **AI-written code.** Claude Code wrote most of the code; the founder set each task and reviewed each change. Agent A's
  claim code in each order is written by DeepSeek V4.1 Flash on NEAR AI Cloud.
- **Libraries.** `near-sdk` and `near-contract-standards` 5.30.0, `base64` 0.22, `serde` 1, `serde_json` 1; tests
  only: `near-sandbox` 0.4.0, `near-api` 0.8.0, `tokio` 1, `rsa` 0.9, `sha2` 0.10, `rand` 0.8; Python: `cryptography`
  and `certifi`. Tools: Rust, `cargo-near` 0.22.0, near-cli-rs. The full table: [docs/near.md](https://github.com/drexthealpha/Knos/blob/v0.4.1/docs/near.md#disclosure).

Everything else (every claim and how to check it, the accounts on NEAR testnet, the tests and attacks, running it
yourself): [docs/near.md](https://github.com/drexthealpha/Knos/blob/v0.4.1/docs/near.md).
<!-- /entry:near -->

<!-- entry:iris -->
## From the InterSystems contest

Inside InterSystems IRIS, a production checks each research step's test result before that step is paid: an AI Hub
agent reads the result, a rule decides, and above $50 a person must also approve.

- Online demo: not hosted yet.
- Video: [the InterSystems Developers YouTube channel](https://www.youtube.com/watch?v=s4YNmcEm-M8); the file,
  [iris/media/knos-iris.mp4](https://github.com/drexthealpha/Knos/blob/v0.4.1/iris/media/knos-iris.mp4) (70 s, with the live AI Hub run of 12 Nov at its end).
- Code: [iris/](https://github.com/drexthealpha/Knos/tree/main/iris); the IPM package is `module.xml` at the root.

### Judge it in 2 minutes

You need Docker with about 4 GB free and the image file `irishealth-community-2026.3.0AI.154.0-docker.tar.gz` from the
[AI Hub Early Access portal](https://evaluation.intersystems.com/Eval/early-access/AIHub) (an InterSystems login).

1. Run, from a clone:

   ```sh
   git clone https://github.com/drexthealpha/Knos && cd Knos/iris
   bash scripts/load-image.sh ~/Downloads/irishealth-community-2026.3.0AI.154.0-docker.tar.gz
   bash scripts/env-secrets.sh && docker compose up -d --build
   bash scripts/ready.sh
   ```

   - see `READY: open http://localhost:52773/knos/ ...` (the first build takes about 3 minutes on 4 cores).
2. Open http://localhost:52773/knos/ and press **A passing test, $20** - see its decision within a few seconds.
3. Press **A passing test, $120** - see it wait for a person; press **Approve** - see it paid in test money.
4. Open Interoperability > Production in the management portal - see `Knos.Iris.Production` with its 22 items, and the
   decision's Visual Trace.

The default run is replay mode: no key and no model download. The live AI Hub run on NEAR AI Cloud, the contest task part
by part, the bonuses, troubleshooting and the architecture: [docs/iris.md](https://github.com/drexthealpha/Knos/blob/v0.4.1/docs/iris.md).
<!-- /entry:iris -->

## From Colosseum

The Colosseum entry is tag v0.3.28 (built 14 Sep to 12 Oct 2026): it checks a coding agent's pull request and pays the
agent on Solana devnet only when the checks GitHub signs have passed.

### Judge it in 2 minutes

1. Open https://drexthealpha.github.io/Knos/check/ - see "The ten-second check" and "Built 14 Sep to 12 Oct 2026 for
   Colosseum (tag v0.3.28)".
2. Paste `https://github.com/drexthealpha/knos-playground/pull/35` into **Pull request** and press **Check** - see
   "Claims nothing about tests; every check passed."
3. Press the link "4PovnMjD...2zcDxt" on that page - see a payment made by Knos's programs on Solana devnet.

The code as entered: https://github.com/drexthealpha/Knos/tree/v0.3.28. More: [docs/colosseum.md](https://github.com/drexthealpha/Knos/blob/v0.4.1/docs/colosseum.md).

## Why

Knos carries research across the valley of death: from a paper nobody has checked to code anyone can trust and use.
The goal: Knos turns any research into a product billions of people use, in days, not years.

The full reference: [docs/near.md](https://github.com/drexthealpha/Knos/blob/v0.4.1/docs/near.md), [docs/iris.md](https://github.com/drexthealpha/Knos/blob/v0.4.1/docs/iris.md) and
[docs/colosseum.md](https://github.com/drexthealpha/Knos/blob/v0.4.1/docs/colosseum.md). MIT licence. Built by drexthealpha, a
solo founder; Knos v1 won the [Sibyl Labs Hackathon](https://hack.sibyllabs.org/leaderboard) (1st of 92).
