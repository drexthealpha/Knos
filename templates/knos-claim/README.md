# knos-claim

Knos turns any research into a product billions of people use, in days, not years.

Knos carries research across the valley of death, toward Kardashev II and III.

Name the Solana address that [Knos](https://github.com/drexthealpha/Knos) pays your GitHub account at. These files
are kept in Knos itself, as `templates/knos-claim/`.

1. Create an empty repository in **your own account** (not an organisation), named `knos-claim`, public, and add
   `.github/workflows/knos-claim.yml` from this folder to it. Or let one command do it: `knos claim <address>` (it
   needs the GitHub CLI, `gh`, signed in, and creates the repository in your account because you ran it).
2. In your new repository open **Actions**, choose **knos claim**, press **Run workflow**, and paste your Solana address yourself.
3. The run asks GitHub for a signed statement that the owner of the repository names that address, and posts it on
   an issue. A relayer carries it to Solana. From then on what your merged pull requests earn through Knos is paid to
   that address.

Run the workflow again with another address to change it. Nothing else starts a claim: no push, no link, no
repository description. An address that arrives in a link could be someone else's, so the address must be one you typed.

The workflow needs no secret and cannot read or change code. What it can do is written at the top of
[the file](.github/workflows/knos-claim.yml).

On Solana devnet today, in test USDC.
