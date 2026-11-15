# idl/: how to call each program

An IDL (interface description) file lists a program's instructions, the accounts each one takes, its data layout and
its error codes. Another program or app reads it to know how to call the program. These files are written by hand
from each program's source (the programs are native Solana programs, not Anchor ones). `tests/test_idl.py` and
`tests/test_pay2_idl.py` hold each file to that source.

| file | program | deployment | devnet address | runs |
|---|---|---|---|---|
| `knos_oidc_v2.json` | knos_oidc, the verifier | second, in use ([`programs-v2/`](../programs-v2)) | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | 2.2 |
| `knos_pay_v2.json` | knos_pay, the [escrow](../docs/WORDS.md#escrow) | second, in use | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | 2.2 |
| `knos_meter.json` | knos_meter, the [meter](../docs/WORDS.md#meter) | second, in use | `FUMKkcE95x2kZUj1zZTCbgcYBmJ3WXPHL8pyA8J6anX` | 1.1 |
| `knos_passkey.json` | knos_passkey, the [passkey](../docs/WORDS.md#passkey) wallet | second, in use | `FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85` | 1.1 |
| `knos_oidc.json` | knos_oidc | first ([`programs/`](../programs)); nobody can change it | `vpWym9azbPU5f2PH2a6n8c4RfmsyUeW2dMuWr1DSHcE` | |
| `knos_pay.json` | knos_pay | first; nobody can change it | `9UzPFbh2A4e4sEPgngKG523FfYLnQ3qPfFVfFTTAdfDi` | |

All of them are on devnet only.

**Two names that mislead.** "_v2" in a file name means the second deployment, not version 2. The `version` field
inside each file is the version of the Knos crates the program was built with (0.3.14), not the program's own version
(the "runs" column).

**Who can change the programs.** The four of the second deployment can be upgraded by a 2-of-3
[multisig](../docs/WORDS.md#multisig), after a public 48-hour delay. Today one person holds all three keys. The first
deployment has no upgrade authority, so nobody can change it. [docs/reference/GOVERNANCE.md](../docs/reference/GOVERNANCE.md) has the
details.

**Known gap.** `knos_oidc_v2.json` does not list the ES256 instructions yet (tags 10 to 15), although the live 2.2 build
runs them. Their accounts and data are in the header of
[`programs-v2/knos_oidc/src/es256.rs`](../programs-v2/knos_oidc/src/es256.rs), and [docs/reference/ES256.md](../docs/reference/ES256.md)
explains them.
