# What Knos will not fund

Every Ready check applies this list, and the demand check refuses a listed idea before it asks Qloo anything. A brief
that names anything on it is refused, not "not ready": no rewrite makes it fundable. The list lives in code
(`src/knos/refuse.py`) and is served at `GET /api/refuse`, so anyone can audit it.

| Category | Why |
|---|---|
| Weapons | arms, munitions and explosives for harm |
| Military first | a product whose first customer or use is military |
| Dangerous pathogens | biological or chemical agents of mass harm, or work that makes a pathogen more dangerous |
| Sanctioned places | places under comprehensive US sanctions: Cuba, Iran, North Korea, and the Crimea, Donetsk and Luhansk regions of Ukraine |

The sanctioned places are those of OFAC's country programs, read on 23 Oct 2026
(https://ofac.treasury.gov/sanctions-programs-and-country-information). Matching is on whole words and phrases, and a
few harmless phrases that share a word are allowed, such as "bath bomb" and "glue gun".

This is a first gate, not a legal review. Before a payout on Solana devnet the workflow also checks the address
against OFAC's SDN list (`src/knos/screen.py`).

Tested by `tests/test_refuse.py`: 30 briefs that are otherwise Ready, each naming one listed word, and 0 of 30 pass.
