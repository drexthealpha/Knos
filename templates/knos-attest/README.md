# knos-attest

Knos turns any research into a product billions of people use, in days, not years.

Knos carries research across the valley of death, toward Kardashev II and III.

Ask GitHub to sign that a [Knos](https://github.com/drexthealpha/Knos) work order's terms were met, so that the person
who did the work can ask for the payment himself. These files are kept in Knos itself, as `templates/knos-attest/`.

1. Create an empty repository in **your own account**, named `knos-attest`, public, and add
   `.github/workflows/knos-attest.yml` from this folder to it (GitHub's **Add file > Create new file**, or the link
   `python -m knos.host_judge editor <you>/knos-attest` prints).
2. In your new repository open **Actions**, choose **knos attest**, press **Run workflow**, and say which repository
   the pull request is in, its number, and the order (its address is on the order's page). Or run
   `knos settle --neutral <pull request url>`, which starts the same run.
3. The run reads GitHub's public record of that pull request and the order on Solana. If the record supports it,
   GitHub signs a statement that names the order, the pull request and the commit, and a relayer carries it to
   Solana, where the payment program pays.

It needs no secret, checks out no code and changes nothing anywhere. What it can do is written at the top of
[the file](.github/workflows/knos-attest.yml), and why a run started by hand in your own repository is trusted.

On Solana devnet today, in test USDC.
