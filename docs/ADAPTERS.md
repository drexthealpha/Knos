# Adapters: other systems' events, and what the chain can check of them

An order is paid when a pinned workflow attests acceptance: GitHub signs a statement about one run, and `knos_pay`
checks that signature and the claims in it. That is the only thing the program believes. So "any signed event can
settle an order" needs a precise reading, and this page gives it:

- **Any event can lead to the attest run.** A deployment, a release, a green workflow, an artifact attestation, an
  issue closed in a tracker: each has an adapter in [`examples/adapters/`](../examples/adapters), a workflow file you copy
  into `.github/workflows/` of the repository the order is for.
- **The chain authenticates the attest run, not the event.** What the other system said reaches the order as a commit
  status that the pinned workflow reads back from GitHub. Who can write that status is trusted. The table says so
  per adapter.
- **Where the program refuses a path, this page says which check refuses it**, under
  [Needs a program change](#needs-a-program-change). Nothing here is claimed beyond `knos_pay` 2.1 and `knos_meter`
  as built. Everything is on Solana devnet with test USDC.

## How an adapter works

1. The event arrives as a GitHub Actions trigger (`deployment_status`, `release`, `workflow_run`, a timer, or a
   `repository_dispatch` another system sends).
2. The adapter finds the pull requests merged in the last 14 days that the event is about, and writes one commit
   status on each one's last commit: `deployed/production`, `released`, `green/deploy`, `attested/build`,
   `tracker/linear-done`, `tracker/jira-done` or `tracker/notion-done`.
3. It starts the repository's own `knos` workflow for that pull request (`gh workflow run knos.yml -f pull=N`). That
   workflow's settle job is the pinned `prove.yml`. It reads GitHub's record again and asks GitHub to sign only when
   every check the order's terms name passed.

To make the event a condition of payment, name the status when the order is funded:

    /knos fund 500 checks: test, deployed/production

The check names are part of the terms, and the terms are hashed into the order at funding
([`src/knos/terms.py`](../src/knos/terms.py)). A status that did not exist on the default branch when the order was
funded is recorded as "from any source": Knos says so in its reply to the funding comment. Without the status in the
terms, an adapter only chooses when the payment is tried.

An adapter holds no `id-token` permission, so it cannot ask GitHub for a signed statement, and it names no Knos
workflow, so it has no commit to keep in step with a release. It writes with two permissions: `statuses: write` and
`actions: write`. Doing its work twice changes nothing: a pull request that already carries the status is skipped.

## The adapters

| event | file | authenticated, and by whom | what remains trusted | status |
|---|---|---|---|---|
| A deployment succeeded (`deployment_status`, state `success`, environment `production`) | [`examples/adapters/deployment.yml`](../examples/adapters/deployment.yml) | The chain: GitHub's signature over the run of the pinned `prove.yml` in the order's own repository. That run: the status `deployed/production` at the pull request's last commit, from GitHub's API. Nobody: the deployment itself. | Whoever can report a deployment status or write a commit status in the repository; the adapter file on the default branch; GitHub's API. GitHub starts no workflow for a deployment status written with the repository's own `GITHUB_TOKEN` ([GitHub's rule](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)): for those, use the next row. | works with 2.1 as built |
| A named workflow finished green on the default branch (`workflow_run`, conclusion `success`) | [`examples/adapters/workflow-run.yml`](../examples/adapters/workflow-run.yml) | The chain: as above. The adapter: GitHub's own record of that run (a push to the default branch, not a fork's run). | The same; and the named workflow's own honesty. | works with 2.1 as built |
| A release was published (`release`, not a draft, not a prerelease) | [`examples/adapters/release.yml`](../examples/adapters/release.yml) | The chain: as above. The adapter: that the tag's commit contains the merge (GitHub's compare). | Whoever can publish a release or write a commit status. | works with 2.1 as built |
| A GitHub artifact attestation exists for the commit | [`examples/adapters/attestation.yml`](../examples/adapters/attestation.yml) | The chain: as above. The adapter, on its runner: `gh attestation verify <file> --repo <owner/name> --source-digest <commit> --deny-self-hosted-runners` for every file the build run uploaded. That checks a Sigstore signature over SLSA provenance (`https://slsa.dev/provenance/v1`) whose subject is the file's sha256, signed for a workflow of this repository, built from this commit ([manual](https://cli.github.com/manual/gh_attestation_verify)). | The adapter's run and the `gh` on its runner: the chain does not verify the Sigstore bundle. And an attestation says where and from what an artifact was built, "not a guarantee that an artifact is secure" ([GitHub](https://docs.github.com/en/actions/concepts/security/artifact-attestations)). | works with 2.1 as built |
| A Linear issue is completed | [`examples/adapters/linear.yml`](../examples/adapters/linear.yml) | The chain: as above. The adapter: Linear's API answer for the issue the pull request names (`state.type` is `completed`), read with a read-only key. Nobody: Linear's webhook. | Linear's API answer as the workflow read it; the repository's secret `LINEAR_API_KEY`; everyone who can change an issue's state in Linear; whoever can write a commit status. | works with 2.1 as built |
| A Jira issue is done | [`examples/adapters/jira.yml`](../examples/adapters/jira.yml) | The chain: as above. The adapter: Jira's API answer (`status.statusCategory.key` is `done`). Nobody: the call Jira makes. | Jira's API answer; the secret `JIRA_API_TOKEN`; everyone who can transition an issue; whoever can write a commit status. If Jira starts the adapter, the token Jira holds: GitHub asks `Contents: write` for a dispatch, so that token can write the repository's files. | works with 2.1 as built |
| A Notion page's status is Done | [`examples/adapters/notion.yml`](../examples/adapters/notion.yml) | The chain: as above. The adapter: Notion's API answer for the page linked in the pull request (`properties.Status.status.name`). Nobody: Notion's webhook. | Notion's API answer; the secret `NOTION_TOKEN`; everyone who can edit the page's status; whoever can write a commit status. | works with 2.1 as built |
| A deployment succeeded, counted and not paid (`knos_meter`) | [`examples/adapters/meter.yml`](../examples/adapters/meter.yml) | `knos_meter`: GitHub's signature over a run of the pinned `attest.yml` at the commit the buyer's Credits name, in a repository the buyer owns, on its first attempt. That run: the pull request was merged. Nobody: the deployment. | The milestone number (2, "deployed") is the adapter's word; whoever can report a deployment status. | works with 2.1 as built |
| A GitLab merge request was merged to a protected branch | [`examples/gitlab/.gitlab-ci.yml`](../examples/gitlab/.gitlab-ci.yml) | The chain: gitlab.com's signature over a job of the pinned CI file at the pinned commit, on a protected branch, in a pipeline that a pipeline of the project started (`programs-v2/knos_pay/src/gl.rs`). That job: the merge request was merged, from GitLab's API. Nobody: the merge event itself. | Everyone who may run a pipeline on the protected branch; GitLab's API answer as the job read it. Tested in LiteSVM with tokens shaped as GitLab documents them (`tests/test_gitlab_pay.py`); it has not run on gitlab.com. `python scripts/gitlab_round.py run` is the whole round as one command ([OIDC.md](OIDC.md), "The round as one command"). | works with 2.1 as built |

## The trackers: no receiver, and what that means

Linear, Jira and Notion sign their webhooks with a secret both sides share (an HMAC). Linear's is the header
`Linear-Signature`, "a hex-encoded HMAC-SHA256 signature of the raw body"
([Linear](https://linear.app/developers/webhooks)). A program on a public chain cannot check such a signature: it
would have to hold the secret, and then anyone could read it and forge the tracker. So the adapters believe nothing
a tracker sends. They ask the tracker's API what state the issue is in now, and act on the answer. No server of
yours or of Knos receives anything.

What can start each one, as the products work today:

| tracker | can it call GitHub's `repository_dispatch` itself? | so the adapter is started by |
|---|---|---|
| Jira | Yes. Jira Automation's "Send web request" action takes a URL, headers, a method and a custom body with smart values ([Atlassian](https://support.atlassian.com/automation/kb/how-to-extend-automation-for-jira-with-rest-api-calls/)). The rule is written out in the adapter's header. | Jira, or a timer every 15 minutes |
| Linear | No. A Linear webhook sends Linear's own headers and no `Authorization` header ([Linear](https://linear.app/developers/webhooks)), and GitHub's API takes no call without one. | a timer every 15 minutes |
| Notion | No. An automation's "Send webhook" action can add a custom header, but it sends "database page properties" as its body and cannot shape it ([Notion](https://www.notion.com/help/webhook-actions)); GitHub's dispatch call requires an `event_type` in the body ([GitHub](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event)). | a timer every 15 minutes |

A dispatch only wakes the adapter. Its payload is never read: whoever holds the dispatching token could put anything
in it.

Plainly, the trust in this path is: the tracker's API answer as read by the workflow; the repository's secret; the
people who can change an issue's state in the tracker. The chain authenticates the workflow that settles. It does
not authenticate the tracker.

## Needs a program change

These are the paths that would bind an event more tightly than a commit status does, and why each does not work
today. The program's rule is one function, `judge` in
[`programs-v2/knos_pay/src/order_judge.rs`](../programs-v2/knos_pay/src/order_judge.rs);
[`tests/test_adapters.py`](../tests/test_adapters.py) runs each refusal against the built program.

**1. Calling the pinned `attest.yml` directly on the event, in the order's own repository.** Refused with
`E_WORKFLOW` (86). The order's own repository is judge a, and judge a takes one file:

    if own && g.wf_file == PROVE { return Ok(Judge::Own); }

**2. Calling the pinned `attest.yml` directly on the event, in any other repository, for a NEUTRAL order.** Refused
with `E_CLAIMS` (85). A neutral run is one a person started by hand in a repository that person owns:

    fn by_hand(g: &Gh) -> bool { g.event == b"workflow_dispatch" && g.actor_id != 0 && g.actor_id == g.owner_id }
    let neutral = o.is(F_NEUTRAL) && !o.is(F_PRIVATE) && by_hand(g);

`event_name` is `deployment_status`, `release`, `workflow_run`, `repository_dispatch` or `schedule` in those runs,
not `workflow_dispatch`. A run that a workflow's own token starts by hand is refused too: its actor is the
Actions bot, not the owner. So a seller cannot automate a neutral attestation from an event without a change here;
the seller starts `knos attest` by hand, as before.

**3. An order whose judge is a repository that attests on any event.** The program has this judge, and it names no
event:

    if named && (g.wf_file == PROVE || g.wf_file == ATTEST) { return Ok(Judge::Private); }

What is missing is not in the program. No `/knos fund` word names a judge repository for a public order (only a
private order gets one, from its attestor), and `knos attest` refuses a private order because its repository is not
on chain. This needs a command and a release of the workflows, not a program change. It is not built.

**4. Calling the pinned `prove.yml` directly on the event, in the order's own repository.** The program would take
the token: judge a reads no event. The pinned `prove.yml` does not sign on it: its settle job runs on a push to the
default branch, `workflow_dispatch`, `schedule` and a comment on a pull request. This needs a new commit of the
workflows, which only orders funded after it would name. The adapters use `workflow_dispatch` instead, which works
today.

**5. The event's own signature, checked on chain.**

- A tracker's webhook: an HMAC under a shared secret. No program change makes it checkable. The tracker would have
  to sign with a private key and publish the public one.
- A GitHub artifact attestation: a Sigstore bundle (a short-lived certificate, a signature over the statement and,
  for public repositories, a transparency log entry). `knos_oidc` verifies RS256 tokens of a workload identity
  issuer. It has no verifier for a Sigstore bundle. That is a new program.
- A token of another issuer: `gh.rs` takes a token only when
  `v.issuer == knos_oidc::pins::ISSUER_GITHUB`, or when a private key's registrant is the wallet whose Balance funded
  a private order. The one exception is a gitlab.com token, and only for a work order: funding one from a Balance
  and paying one (`gl.rs`; [OIDC.md](OIDC.md) has the claims). Every other instruction refuses a GitLab token
  (`E_TOKEN`), a 2.0 job's payment included, and a token of any other issuer is refused everywhere, although
  `knos_oidc` can verify it.

**6. The meter's milestone as a fact about the event.** `knos_meter` counts what the pinned `attest.yml` signed: a
pull request was merged, or closed unmerged. The milestone is a number in the audience. "Milestone 2 means
deployed" is a convention between buyer and seller, not something the meter checks.

## What was run

- `tests/test_adapters.py`: every adapter parses, passes `actionlint` 1.7.12, holds no `id-token` permission and
  puts nothing of an event into a script; each script runs against a stand-in for `gh` and for the tracker's API
  (marks the right pull requests, once); `knos_pay` in LiteSVM pays on the run an adapter starts and refuses paths
  1 and 2 with the codes above.
- Not run: no adapter has run on GitHub against a live deployment, Linear, Jira or Notion. The API calls are written
  from the vendors' documentation linked above.
