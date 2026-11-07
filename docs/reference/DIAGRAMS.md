# Knos diagrams

The source of each picture in README.md. Pages that cannot draw Mermaid (Open Exchange, PyPI) show the picture, drawn by `python scripts/diagrams.py render`.

## How it works

```mermaid
flowchart TB
    idea["A paper or an idea"] --> demand["Demand check on Qloo: who wants it, the launch city and the pre-order target"]
    demand --> ready["Ready brief: each milestone has a target, a checker and a deadline, locked by a hash"]
    ready --> held["Backers pre-order or fund milestones; the money is held on Solana devnet"]
    held --> proof["The maker sends the proof for one milestone"]
    proof -->|verified| paid["The maker is paid for that milestone"]
    proof -->|not verified by the deadline| back["Nobody is paid; the money goes back to the backers"]
```

*No money locks on a vague brief. Each step is paid only when its proof is verified.*

## Paid on proof

```mermaid
flowchart TB
    held["The money is held on Solana devnet"] --> proof["The maker sends the proof for one milestone"]
    proof -->|verified| paid["The program pays the maker for that milestone"]
    proof -->|not verified by the deadline| back["The program refunds every backer"]
```

*Nothing is paid on a promise. A missed deadline sends the money back.*

## Run it on IRIS

```mermaid
flowchart LR
    gh["Check run (webhook or poller)"] --> pin["ProofIn"]
    lab["FHIR Observation or HL7 ORU"] --> pin
    ver["Referee verdict"] --> pin
    pin --> bp["ProofDecision (BPL)"]
    bp --> hash["Brief hash vs lock (Knos, Embedded Python)"]
    bp --> ref["Referee: AI Hub agent on a local model"]
    bp --> gate["PayoutGate"]
    gate -->|HUMAN| wf["Workflow: PayoutApprovers"]
    gate -->|PAY| sol["SolanaRead, then SolanaSubmit (Java PEX)"]
    bp --> trace["Span messages in Visual Trace"]
```

*Proof arrives one of three ways; one process checks, asks the agent, gates, asks a person, then simulates.*

## Knos on NEAR

```mermaid
flowchart LR
    post["A job: its bid held in a NEAR contract against a locked test"] --> try["Two agents take it and submit"]
    try --> check["The checker runs the locked test on each output"]
    check -->|passes| paid["The contract pays that agent"]
    check -->|fails| zero["That agent is paid 0"]
```

*One job, two agents: only the output that passes the locked test is paid.*
