# Knos diagrams

The source of each picture in README.md. Pages that cannot draw Mermaid (Open Exchange, PyPI) show the picture, drawn by `python scripts/diagrams.py render`.

## How it works

```mermaid
flowchart TB
    idea["A research idea"] --> demand["Is it wanted? Knos asks who would buy it, and where"]
    demand --> ready["Each step gets a goal and a deadline, plus the test that decides it, sealed so nobody can change them"]
    ready --> held["Backers fund the steps; the money waits on a public ledger"]
    held --> proof["The maker sends proof for one step"]
    proof -->|the test passes| paid["That step is paid"]
    proof -->|no pass by the deadline| back["Nobody is paid; the backers get their money back"]
```

*Money moves only when a step passes its test.*

## Paid on proof

```mermaid
flowchart TB
    held["The money waits on a public ledger, not with Knos"] --> proof["The maker sends proof for one step"]
    proof -->|the test passes| paid["The ledger's program pays the maker for that step"]
    proof -->|no pass by the deadline| back["The program gives every backer their money back"]
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
