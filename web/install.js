// Install Knos by one pull request. renderInstall(el) draws one text box, "owner/repo": it builds the link that opens
// GitHub's own editor with .github/workflows/knos.yml filled in (GitHub then offers the branch and the pull request),
// shows the exact file, a second link for a private repository's attestor, and the terms templates with the comment
// to copy. Nothing is sent anywhere: the page only writes links. The file is short because a link holds at most
// 8,191 bytes (https://github.com/github/docs/issues/5136).
// The three constants below are written from examples/ by scripts/front_workflow.py and by nothing else.
export const INSTALL_WORKFLOW = `# .github/workflows/knos.yml: \`/knos fund 20\` on an issue funds it; the merged pull request that closes it is paid. No secret. What each line does: examples/knos-workflow.yml in drexthealpha/Knos
name: knos
on:
  issue_comment: {types: [created]}
  issues: {types: [opened]}
  push: {branches: ["**"]}
  workflow_dispatch: {inputs: {pull: {description: Number of the merged pull request whose payment to try again, required: true, type: number}}}
  workflow_run: {workflows: [knos check], types: [completed]}
permissions: {}
jobs:
  command:
    name: knos command
    permissions: {contents: read, issues: write, pull-requests: write, checks: read, statuses: read, actions: read, id-token: write}
    if: (github.event_name == 'issue_comment' && (startsWith(github.event.comment.body, '/knos') || contains(github.event.comment.body, fromJSON('"\\n/knos"')))) || (github.event_name == 'issues' && (contains(github.event.issue.body, '/knos fund') || contains(github.event.issue.body, '/knos bounty')))
    uses: drexthealpha/knos-workflows/.github/workflows/fund.yml@160edd4e19fcfbc86f712f01225e0717a7dde2d7
  settle:
    name: knos settle
    needs: command
    permissions: {contents: read, issues: write, pull-requests: write, checks: read, statuses: read, actions: read, id-token: write}
    if: github.event_name != 'issues' && !cancelled() && (github.event_name != 'issue_comment' || needs.command.outputs.settle != '') && (github.event_name != 'push' || github.ref == format('refs/heads/{0}', github.event.repository.default_branch))
    uses: drexthealpha/knos-workflows/.github/workflows/prove.yml@160edd4e19fcfbc86f712f01225e0717a7dde2d7
`;
export const ATTESTOR_WORKFLOW = `# .github/workflows/knos-attestor.yml, without its comments: read them in examples/knos-attestor.yml of drexthealpha/Knos
name: knos attestor
on:
  schedule:
    - cron: "*/15 * * * *"
  workflow_dispatch:
    inputs:
      repository:
        description: "One target, as owner/name (empty: every repository the policy lists)"
        required: false
        type: string
        default: ""
      issue:
        description: "Optional: the number of the issue whose /knos fund comment to answer now"
        required: false
        type: string
        default: ""
      pull:
        description: "Optional: the number of the merged pull request whose payment to try now"
        required: false
        type: string
        default: ""
permissions: {}
jobs:
  command:
    name: knos command
    permissions:
      contents: read
      issues: write
      pull-requests: write
      checks: read
      statuses: read
      actions: read
      id-token: write
    uses: drexthealpha/knos-workflows/.github/workflows/fund.yml@160edd4e19fcfbc86f712f01225e0717a7dde2d7
    secrets:
      KNOS_READ_TOKEN: \${{ secrets.KNOS_READ_TOKEN }}
      KNOS_RELAY_KEY: \${{ secrets.KNOS_RELAY_KEY }}       # optional: when the repository has none, this passes nothing
  settle:
    name: knos settle
    needs: command    # after the funding, so that an order funded in this run is there when its pull request is read
    if: >-
      !cancelled()
    permissions:
      contents: read
      issues: write
      pull-requests: write
      checks: read
      statuses: read
      actions: read
      id-token: write
    uses: drexthealpha/knos-workflows/.github/workflows/prove.yml@160edd4e19fcfbc86f712f01225e0717a7dde2d7
    secrets:
      KNOS_READ_TOKEN: \${{ secrets.KNOS_READ_TOKEN }}
      KNOS_RELAY_KEY: \${{ secrets.KNOS_RELAY_KEY }}       # optional, as above
`;
export const TERMS = [{"name":"bugfix","sentence":"Pays 50 test USDC when checks `lint`, `unit` pass on a merge that only touches src/ and tests/; refund after 14 days","comment":"/knos fund 50 checks: unit, lint paths: src/**, tests/**","where":"an issue","terms":{"accept":"","checks":[{"app":15368,"name":"lint"},{"app":15368,"name":"unit"}],"deny":[".github/**",".knos/**"],"mode":"merge","paths":["src/**","tests/**"],"reserve":7,"v":1},"terms_json":"{\"accept\":\"\",\"checks\":[{\"app\":15368,\"name\":\"lint\"},{\"app\":15368,\"name\":\"unit\"}],\"deny\":[\".github/**\",\".knos/**\"],\"mode\":\"merge\",\"paths\":[\"src/**\",\"tests/**\"],\"reserve\":7,\"v\":1}","terms_hash":"91c3adb2adc12c66beb852fe809a096d4dd7028c0bc77ec209b6879ca753f2e3","assumes":{"checks":"each named check is a GitHub Actions job (GitHub App 15368) that ran on the default branch's latest commit"}},{"name":"feature-blackbox","sentence":"Pays 80 test USDC when check `unit` passes on a pull request that also passes the issue's black-box acceptance suite; refund after 14 days","comment":"/knos fund 80 checks: unit","where":"an issue that has .knos/acceptance/<issue>/ on the default branch","terms":{"accept":"5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d","checks":[{"app":15368,"name":"unit"}],"deny":[".github/**",".knos/**"],"mode":"tests","paths":[],"reserve":7,"v":1},"terms_json":"{\"accept\":\"5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d\",\"checks\":[{\"app\":15368,\"name\":\"unit\"}],\"deny\":[\".github/**\",\".knos/**\"],\"mode\":\"tests\",\"paths\":[],\"reserve\":7,\"v\":1}","terms_hash":"59bd9e078eaa2b7d2d92d489d6f1bdd72f7f01e800dd9dd484b210bb82e4aab6","assumes":{"checks":"each named check is a GitHub Actions job (GitHub App 15368) that ran on the default branch's latest commit","accept":"a sample hash: yours is the hash of your own acceptance bundle"}},{"name":"milestone","sentence":"Pays 100 test USDC when check `unit` passes on a merge; 20% of it waits 30 days and goes back if the change is reverted; refund after 30 days","comment":"/knos fund 100 checks: unit holdback 20 warranty 30 days 30","where":"an issue","terms":{"accept":"","checks":[{"app":15368,"name":"unit"}],"deny":[".github/**",".knos/**"],"mode":"merge","paths":[],"reserve":7,"v":1},"terms_json":"{\"accept\":\"\",\"checks\":[{\"app\":15368,\"name\":\"unit\"}],\"deny\":[\".github/**\",\".knos/**\"],\"mode\":\"merge\",\"paths\":[],\"reserve\":7,\"v\":1}","terms_hash":"d48a34bb43bc57e8c0fb46b9981c939c0648cec80f598efcf444f337b783a8d0","assumes":{"checks":"each named check is a GitHub Actions job (GitHub App 15368) that ran on the default branch's latest commit"}},{"name":"private-attested","sentence":"Pays 50 test USDC when check `unit` passes on a merge that only touches src/; funded and paid by the organisation's attestor repository, so nothing public names the private one; refund after 14 days","comment":"/knos fund 50 checks: unit paths: src/**","where":"an issue of a private repository the attestor's policy lists","terms":{"accept":"","checks":[{"app":15368,"name":"unit"}],"deny":[".github/**",".knos/**"],"mode":"merge","paths":["src/**"],"policy":"f2ab964fdea7849f5726192ae7f6b6d7603da31174a51f4c76d2b6dfffc9504d","reserve":7,"v":1},"terms_json":"{\"accept\":\"\",\"checks\":[{\"app\":15368,\"name\":\"unit\"}],\"deny\":[\".github/**\",\".knos/**\"],\"mode\":\"merge\",\"paths\":[\"src/**\"],\"policy\":\"f2ab964fdea7849f5726192ae7f6b6d7603da31174a51f4c76d2b6dfffc9504d\",\"reserve\":7,\"v\":1}","terms_hash":"6053bb7383ac533926cde0864f7c3a56963d730d45d9d0a6154bae46313642c5","assumes":{"checks":"each named check is a GitHub Actions job (GitHub App 15368) that ran on the default branch's latest commit","policy":"the attestor repository's .knos/policy.yml is: version: 1; private: true; attestor: acme/knos-settle; targets: [acme/vault-core]"}},{"name":"standing-rate","sentence":"Pays @octocat 10 test USDC for each pull request of theirs, up to 100 test USDC in all, when check `unit` passes on a merge; refund after 90 days","comment":"/knos offer @octocat rate 10 budget 100 checks: unit days 90","where":"an issue","terms":{"accept":"","checks":[{"app":15368,"name":"unit"}],"deny":[".github/**",".knos/**"],"mode":"merge","paths":[],"reserve":0,"v":1,"vendor":583231},"terms_json":"{\"accept\":\"\",\"checks\":[{\"app\":15368,\"name\":\"unit\"}],\"deny\":[\".github/**\",\".knos/**\"],\"mode\":\"merge\",\"paths\":[],\"reserve\":0,\"v\":1,\"vendor\":583231}","terms_hash":"357edc2100129d5f8ecd0c985901662f6be80e46ce2ae7c22a381bc94192c49e","assumes":{"checks":"each named check is a GitHub Actions job (GitHub App 15368) that ran on the default branch's latest commit","vendor":"@octocat (account id 583231) stands for your vendor"}}];

export const URL_LIMIT = 8191;
const SPEC = /^(?:https:\/\/github\.com\/)?([A-Za-z0-9](?:-?[A-Za-z0-9]){0,38})\/([A-Za-z0-9._-]{1,100}?)(?:\.git)?\/?(?:@([A-Za-z0-9._\/-]{1,200}))?$/;

// { owner, repo, branch } from "owner/repo" or "owner/repo@branch" (the branch is main unless named); null otherwise.
export function parseRepo(text) {
  const m = SPEC.exec(String(text || "").trim());
  return m && m[2] !== "." && m[2] !== ".." ? { owner: m[1], repo: m[2], branch: m[3] || "main" } : null;
}

// Every byte but the unreserved ones as %XX: what Python's urllib.parse.quote(text, safe="") gives, so `knos init --pr`
// and this page print the same link.
const quote = (s) => encodeURIComponent(s).replace(/[!'()*]/g, (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase());

// The link that opens GitHub's editor in that repository with `text` as a new file at `path`; null when the
// repository is not one or GitHub would refuse the link for its length.
export function installLink(spec, text = INSTALL_WORKFLOW, path = ".github/workflows/knos.yml") {
  const at = typeof spec === "string" ? parseRepo(spec) : spec;
  if (!at) return null;
  const url = `https://github.com/${at.owner}/${at.repo}/new/${at.branch.split("/").map(quote).join("/")}?filename=${quote(path)}&value=${quote(text)}`;
  return url.length > URL_LIMIT ? null : url;
}
export const attestorLink = (spec) => installLink(spec, ATTESTOR_WORKFLOW, ".github/workflows/knos-attestor.yml");

// True when every workflow the file calls is named by a full commit: a file that still holds a placeholder is shown, never linked.
export const pinnedFile = (text) => { const refs = [...text.matchAll(/^\s*uses:\s*\S+@(\S+)/gm)].map((m) => m[1]); return refs.length > 0 && refs.every((r) => /^[0-9a-f]{40}$/.test(r)); };

const node = (doc, tag, props = {}, kids = []) => { const n = doc.createElement(tag); Object.assign(n, props); for (const k of kids) n.append(k); return n; };

function copyButton(doc, text, label = "Copy") {
  const b = node(doc, "button", { type: "button", className: "small ghost", textContent: label });
  b.addEventListener("click", async () => {
    try { await globalThis.navigator.clipboard.writeText(text); b.textContent = "Copied"; }
    catch { b.textContent = "Select the text and copy it"; }
  });
  return b;
}

export function renderInstall(el) {
  const doc = el.ownerDocument;
  const input = node(doc, "input", { type: "text", id: "install-repo", autocomplete: "off", placeholder: "owner/repo" });
  const out = node(doc, "div", { id: "install-result" });
  out.setAttribute("role", "status"); out.setAttribute("aria-live", "polite");
  const show = () => {
    out.replaceChildren();
    if (!String(input.value || "").trim()) return;
    const at = parseRepo(input.value);
    if (!at) { out.append(node(doc, "p", { className: "status bad", textContent: "Write the repository as owner/repo (or owner/repo@branch when its default branch is not main)." })); return; }
    const link = pinnedFile(INSTALL_WORKFLOW) ? installLink(at) : null, attestor = pinnedFile(ATTESTOR_WORKFLOW) ? attestorLink(at) : null;
    if (!link) { out.append(node(doc, "p", { className: "status bad", textContent: "This copy of the page has no published workflow commit yet, so it gives no link. The file is below to read." })); return; }
    out.append(
      node(doc, "p", {}, [node(doc, "a", { className: "button", id: "install-open", href: link, target: "_blank", rel: "noopener", textContent: `Open the pull request in ${at.owner}/${at.repo}` })]),
      node(doc, "p", { className: "fine", textContent: `GitHub opens its editor with .github/workflows/knos.yml filled in. Press "Commit changes", choose "Create a new branch and start a pull request" (GitHub offers a fork instead when you cannot write to ${at.owner}/${at.repo}), and merge it. This page sent nothing: the link is the whole install.` }));
    if (attestor) out.append(node(doc, "p", { className: "fine" }, [
      "A private repository runs no Knos file. One repository of the organisation is its attestor: ",
      node(doc, "a", { id: "install-attestor", href: attestor, target: "_blank", rel: "noopener", textContent: `open the attestor's file in ${at.owner}/${at.repo}` }),
      ". That repository also needs .knos/policy.yml (private: true, attestor, targets) and the secret KNOS_READ_TOKEN, which reads the private repositories it attests for."]));
  };
  input.addEventListener("input", show);
  const file = node(doc, "details", {}, [node(doc, "summary", { className: "fine", textContent: `The exact file (${INSTALL_WORKFLOW.split("\n").length - 1} lines)` }),
    node(doc, "pre", { id: "install-file", textContent: INSTALL_WORKFLOW }), copyButton(doc, INSTALL_WORKFLOW, "Copy the file")]);
  const terms = node(doc, "div", { id: "install-terms" }, [node(doc, "h3", { textContent: "Then fund an issue: terms from a template" })]);
  for (const t of TERMS) terms.append(node(doc, "div", { className: "card" }, [
    (() => { const p = node(doc, "p", {}, [node(doc, "strong", { textContent: t.name }), `: ${t.sentence}.`]); p.setAttribute("data-keep", ""); p.setAttribute("data-not-prose", ""); return p; })(),
    node(doc, "pre", { textContent: t.comment }), copyButton(doc, t.comment, "Copy the comment"),
    node(doc, "details", {}, [node(doc, "summary", { className: "fine", textContent: "The terms it funds" }), node(doc, "pre", { textContent: `${t.terms_json}\nsha256 ${t.terms_hash}` }),
      node(doc, "p", { className: "fine", textContent: `Post it on ${t.where}. These bytes were made with sample facts (${Object.values(t.assumes).join("; ")}); the reply to your comment shows your repository's own terms.` })])]));
  el.replaceChildren(node(doc, "label", { htmlFor: "install-repo", textContent: "Install by pull request: your repository" }), input, out, file, terms);
  show();
}
