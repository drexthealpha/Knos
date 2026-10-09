# Collecting a held payout

A merged pull request pays the address bound to its author's GitHub account. With none bound, knos_pay holds the
money for that account, and the reply on the pull request links to `#payee=<login>` on the site (web/payee.js).

## What the page does

1. Reads what is held for the login: held jobs (their amount less the job fee) and held orders (what they have not
   paid yet), found on devnet by the account's numeric GitHub id.
2. Makes a passkey in the browser (WebAuthn, P-256). Its address is a knos_passkey account: no seed phrase, no
   wallet app. The address is copied. The Get paid page (`#claim`) withdraws from the same address later.
3. Gives one link: GitHub's new-repository form filled in from the template `drexthealpha/knos-claim` (owner, name
   `knos-claim`, public) while that repository does not exist; the claim workflow's page once it does.
4. Check reads the account's Bind on devnet and says whether it names this passkey's address. The relay then sends
   what was held.

The page signs and sends nothing. It reads api.github.com and Solana devnet, only when opened.

## Clicks to a first payout

| | Before (docs, wallet app) | Now (`#payee`) |
| --- | --- | --- |
| Address | install a wallet app; create a wallet and write down its seed phrase; copy its address (3) | Make a passkey; confirm on the device (2; the address is copied) |
| Repository | open the template; Use this template; Create a new repository; type the name; Create repository (5) | the page's link; Create repository (2) |
| Bind | Actions; knos claim; Run workflow; paste the address; Run workflow (5) | the page's link; Run workflow; paste the address; Run workflow (4) |
| Total | 13 | 8 (4 when the repository exists already) |

Counted on the screens as `web/payee.js` `CLICKS` lists them; tests/web/payee.mjs checks the page shows 13 and 8.

## Why it is not one click

The deployed knos_pay (2.1, and 2.2 after proposals 7 and 8: the rule is unchanged since 0.3.12) takes a Bind token
only from the pinned claim workflow, in the account's own repository named `knos-claim`, in a run its owner started
by hand (`workflow_dispatch`, first attempt): `programs-v2/knos_pay/src/pay.rs`, `bind`. A push does not count, not
even the first push of a repository made from the template. That is deliberate: GitHub's new-repository form can be
filled in from a link ([query parameters](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)),
so a push could carry an address the link's author chose, made with the owner's click. The address must be the run's
input, pasted by its owner. So the template's workflow keeps `workflow_dispatch` as its only trigger.

A push workflow that starts the claim workflow with `GITHUB_TOKEN` would run (GitHub lets `GITHUB_TOKEN` create
`workflow_dispatch` runs: [triggering a workflow](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)),
but its address would come from the repository, which is the hole above. Knos does not do it.

## What a program change would need (not made)

Fewer clicks safely needs an address that GitHub shows the owner typed, from somewhere a link cannot fill. A comment
on an existing issue is one: GitHub fills a new issue's body from a link but not a comment box. A new knos_pay
instruction could take a bind token from a pinned Knos workflow on `issue_comment` (created, not edited), with
`actor_id` the commenter, carrying `knos2:bind:<address>` from the comment. The payee would then make a passkey, paste
`/knos address <address>` as a comment on the pull request and press Comment: 4 clicks, no repository. That is a
program upgrade (multisig, public 48-hour delay) and is not in this release.
