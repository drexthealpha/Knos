# Customer-hosted: the record API, the relay and the approver in the buyer's own cloud

**The neutral meter for AI agent work: neither side keeps the count.**

Knos hosts no server. A buyer that wants one runs it: one image, three roles, one config file. This page says what
the bundle is, how to start it, and what it does not do yet. Two limits, first: **it has not been run in any cloud**
(it is built and checked here, `tests/test_selfhost.py`, with no network), and **there is no single sign-on in it**:
its ports listen on 127.0.0.1 only, for the buyer's own identity proxy to put in front (section 4).

| file | what it is |
|---|---|
| `deploy/Dockerfile` | the one image: bases pinned by digest, every Python package installed by its hash |
| `deploy/compose.yaml` | three services of that image: `record`, `relay`, `site` |
| `deploy/knos.example.toml` | the one config file, to copy to `deploy/knos.toml` |
| `src/knos/selfhost.py` | `knos selfhost check`, `knos selfhost plan`, and what each container runs |

## 1. The three roles

| service | what it runs | port (on 127.0.0.1) | key files it reads |
|---|---|---|---|
| `record` | the record API, `knos record serve` ([RECORD.md](RECORD.md) section 5) on the buyer's record files | 8402 | `keys.record` (signs paid answers; without it answers say they are unsigned) |
| `relay` | the relay worker, `knos relay --serve` ([RELAY.md](RELAY.md)), carrying tokens posted in the buyer's repositories and paying the fees from the **buyer's own** fee payer | none | `keys.relay` (and `keys.relay_more`: one fee account per order in flight), `keys.github_token` |
| `site` | the static site, built into the image from the commit named, with the approver at `#approve`; the approver reads the files a person drops on it and asks no other host | 8080 | none |

A relay decides nothing: the money goes where the token says, and the program takes a token once. Running your own
relay changes who pays the transaction fees, not who can be paid.

## 2. The config: `knos.toml`

One TOML file (`deploy/knos.example.toml` is a complete one): `[chain]` (cluster, RPC, and program ids only when
trying a staging deployment), `[keys]`, and one table per role. Every key is named **by file path**; a value that
looks like a key itself is refused, and so is mainnet, an unknown table or setting, and a role without the key it
needs. When a container starts, it checks the file again, reads each key file, and hands it to the role in the
variable that role already reads (`KNOS_RELAY_KEY`, `KNOS_RELAY_KEYS`, `GH_TOKEN`). The key files are mounted
read-only from `deploy/secrets/`, which `deploy/.gitignore` keeps out of git.

```
cp deploy/knos.example.toml deploy/knos.toml          # then edit it
knos selfhost check deploy/knos.toml                  # what will run, which key files it reads; --files: they must exist here
knos selfhost plan deploy/knos.toml                   # the compose services, and the command that starts them
KNOS_COMMIT=$(git rev-parse HEAD) docker compose -f deploy/compose.yaml up -d --build record relay site
```

Without the CLI's own dependencies, `python -m knos.selfhost check|plan` is the same command.

## 3. The image

`python:3.12-slim` by its digest, as Docker Hub listed it on 6 October 2026
(`sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f`,
[Docker Hub](https://hub.docker.com/v2/namespaces/library/repositories/python/tags/3.12-slim)). Into it, with
`--require-hashes --no-deps --only-binary :all:`: `requirements/faucet.txt` (solders and the memory engine) and the
last line of `requirements/sign.txt`, the released knos wheel and its hash. No source tree is installed. The image
needs a wheel that has `knos.selfhost` (0.3.23 on); the build stops when the locked one does not. The containers run
as an unprivileged user, with a read-only root file system, every capability dropped, and a volume per service for
its state (the record API's lookup counts, kept in the memory engine; the relay's notes).

## 4. Single sign-on: not built; the plan

The bundle authenticates nobody. The record API is paid per call by signature and the site is static, but the
approver and the record API are meant for the buyer's own staff and machines. The plan is to put them behind the
identity proxy the buyer already runs, which signs people in with the buyer's OpenID Connect provider and forwards
only signed-in requests to 127.0.0.1:8080 and 127.0.0.1:8402. Any of these does it:

- [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/), a reverse proxy that authenticates through providers,
  [OpenID Connect among them](https://oauth2-proxy.github.io/oauth2-proxy/configuration/providers/openid_connect);
- [Pomerium](https://www.pomerium.com/docs/capabilities/authentication), which works with any identity provider that
  uses OpenID Connect;
- on AWS, an [Application Load Balancer](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/listener-authenticate-users.html),
  which authenticates users through an OpenID Connect identity provider before it forwards a request.

None of these has been configured or tried with this bundle.

## 5. What is not here

Not run in any cloud; no single sign-on; no provisioning, backup or monitoring; no support commitment. The price
book's Enterprise line stays "not deliverable yet" until those exist. Mainnet is refused.
