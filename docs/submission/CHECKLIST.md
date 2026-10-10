# What each entry needs

The Crypto World's Fair runs from 14 Sep to 12 Oct 2026; submissions are due 12 Oct 2026
([colosseum.com/worldsfair](https://colosseum.com/worldsfair), read 9 Oct 2026). Knos enters three ways. The form's
fields are in [SUBMISSION.md](SUBMISSION.md); its day-of-submission checks are there too.

## Every entry: the form

From [colosseum.com/hackathon](https://colosseum.com/hackathon) (read 9 Oct 2026):

- [ ] Product name and a short description: the one sentence ([SUBMISSION.md](SUBMISSION.md), `whatBuilding`).
- [ ] The chains and tools it integrates: Solana devnet, GitHub Actions OIDC (`chains`, `chainUsage`).
- [ ] Every teammate, with background, and the team's location: one person ([../TEAM.md](../TEAM.md)).
- [ ] A logo: `web/brand/`.
- [ ] The GitHub repository at the release tag, opened signed out: [`github.com/drexthealpha/Knos/tree/v0.3.25`](https://github.com/drexthealpha/Knos/tree/v0.3.25).
      Never the bare repository address: a cached copy of its front page can show an older release.
- [ ] A presentation video: the render of [`pitch_script_120.md`](pitch_script_120.md), which ends before two minutes.
      The form's help text says `Up to 2 minutes`; Colosseum's page says two to three. At just under two
      minutes the cut meets the form; the founder decides if the page's lower bound matters more.
- [ ] A demo video of no more than three minutes ([demo_script.md](demo_script.md)).
- [ ] Go-to-market, demand validation and distribution (`marketValidation`, `traction`: zeros stay zeros).
- [ ] Past work disclosed in the form itself (`repoContext`).
- [ ] Weekly one-minute updates: recommended, not required ([weekly_update.md](weekly_update.md)).

## Links, field by field

Which link goes in which field is in [SUBMISSION.md](SUBMISSION.md) ("Which link goes in which field"): the
repository field gets the tag, [`github.com/drexthealpha/Knos/tree/v0.3.25`](https://github.com/drexthealpha/Knos/tree/v0.3.25); `liveProductLink` names the site first; any other
place for a link gets the judges' page at the tag, [`docs/JUDGES.md` at `v0.3.25`](https://github.com/drexthealpha/Knos/blob/v0.3.25/docs/JUDGES.md).

## What only the founder fills in

- [ ] **The two videos are uploaded by the founder to YouTube, Loom or Vimeo.** The form takes links from those three
      hosts only (its help text, read signed in on 9 Oct 2026). Upload the render of
      [`pitch_script_120.md`](pitch_script_120.md) as the presentation and the render of [demo_script.md](demo_script.md)
      as the demo; set each so that anyone with the link can watch it, and open both signed out before pasting.
      The form's help text says a video link cannot be changed after the form is submitted: paste the final ones.
- [ ] **Country**: the founder's own answer.
- [ ] **Telegram**: the founder's own handle.
- [ ] **Accelerator**: the founder's own choice.

Nothing in this repository can answer these four, and nothing here submits the form.

## Grand Prize

30,000 USD, and 15,000 USD to each of the next 20 projects, judged across all chains
([colosseum.com/worldsfair](https://colosseum.com/worldsfair)). Every submission is eligible; nothing to tick.

- [ ] The pitch leads with the strict count from `docs/facts.json`.
- [ ] One transaction told end to end: [TRANSACTION.md](TRANSACTION.md).

## Solana track

100,000 USD: 10 projects receive 10,000 USD each, in addition to the main awards
([colosseum.com/worldsfair](https://colosseum.com/worldsfair)).

- [ ] The Solana ecosystem track is selected in the form.
- [ ] Program ids and the release manifest named: [../MANIFEST.md](../MANIFEST.md).
- [ ] Why Solana in one line: the sentence in [../JUDGES.md](../JUDGES.md).

## Public Good

5,000 USD ([colosseum.com/worldsfair](https://colosseum.com/worldsfair)). The page states no criteria; if the form has
no place to enter it, ask Colosseum before 12 Oct how to be considered.

The entry is knos_oidc as a primitive any Solana program can use: it checks a GitHub or GitLab OIDC token's RS256
signature on chain and leaves the claims in an account.

- [ ] The interface crate, MIT, published at 0.3.14: [crates/knos-oidc-interface](../../crates/knos-oidc-interface/README.md).
- [ ] The IDL: [idl/knos_oidc_v2.json](../../idl/knos_oidc_v2.json).
- [ ] An example program that reads a verified token: [examples/oidc_gate](../../examples/oidc_gate/README.md),
      and a template: [examples/reader_template](../../examples/reader_template/README.md).
- [ ] From another program, step by step: [../COMPOSE.md](../COMPOSE.md).
- [ ] Said plainly: no program outside this repository reads a token yet (`docs/facts.json`,
      `outside_programs_reading_the_verifier`: 0).
