# knos-claim (for an organisation)

Knos turns any research into a product billions of people use, in days, not years.

Knos carries research across the valley of death, toward Kardashev II and III.

Name the Solana address that [Knos](https://github.com/drexthealpha/Knos) pays your GitHub **organisation** at.
A personal account uses `templates/knos-claim/` instead. These files are kept in Knos itself, as `templates/knos-claim-org/`.

1. Create a repository in **the organisation**, named `knos-claim`, and add `.github/workflows/knos-claim.yml` from
   this folder to it (or run `knos claim --org <organisation> <address>`, which does both because you ran it).
2. Give write access to it only to the people you trust with where the organisation's payments go: everyone who can
   start a workflow by hand here can name the address.
3. In the new repository open **Actions**, choose **knos claim**, press **Run workflow**, and paste the address
   yourself.
4. The run asks GitHub for a signed statement that a member started it in the organisation's repository and names
   that address, and posts it on an issue. A relayer carries it to Solana. From then on what is owed to the
   organisation through Knos is paid to that address.

Run the workflow again with another address to change it. Nothing else starts a claim: no push, no link, no
repository description.

The workflow needs no secret and cannot read or change code. What it can do is written at the top of
[the file](.github/workflows/knos-claim.yml).

On Solana devnet today, in test USDC.
