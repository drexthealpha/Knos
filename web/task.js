// A task with no repository: a title, a description, an amount and five or more pairs of an input and the answer it must
// get. This page makes the files and the text; it sends nothing. Every result is a link to a GitHub page that is already
// filled in (a repository made from the template, a new issue, three new files) and the comment that funds the issue, and a
// person presses the last button on GitHub. What is made here:
//
//   .knos/acceptance/<issue>/blackbox.py, cases.json, README.md
//
// the black-box acceptance bundle of `knos accept init` (src/knos/accept.py): the judge runs "$KNOS_RUN <command>" in the pull
// request's tree on each input and compares what it prints with the recorded answer. The three files are those that
// accept.bundle writes, byte for byte (tests/test_accept.py holds the recorded copies this file is tested against), with the
// answers given by the person instead of recorded from a reference command: nothing here ran a reference.

export const TEMPLATE = "drexthealpha/knos-task";
export const MIN_PAIRS = 5;
export const MAX_PAIRS = 200;        // src/knos/accept.py MAX_CASES: one run of the command per case, each in the judge's sandbox
export const MAX_INPUT = 2000;       // src/knos/accept.py MAX_INPUT: characters of one input line
export const MAX_URL = 6000;         // the longest link a new-file page is given the file in; a longer file is pasted by hand

// ---- the command line, as Python's shlex.split(posix=True) reads it ---------------------------------------------------------
// Words are separated by spaces, tabs and line ends; '...' keeps everything; "..." keeps everything but lets a backslash
// escape a quote or a backslash; outside quotes a backslash escapes the next character. Throws on an open quote or a
// backslash at the end, as shlex does.
export function shellSplit(text) {
  const out = [];
  let word = null, i = 0;
  const s = String(text);
  while (i < s.length) {
    const c = s[i];
    if (" \t\r\n".includes(c)) { if (word !== null) { out.push(word); word = null; } i++; continue; }
    word ??= "";
    if (c === "\\") { if (i + 1 >= s.length) throw new Error("No escaped character"); word += s[i + 1]; i += 2; }
    else if (c === "'") { const end = s.indexOf("'", i + 1); if (end < 0) throw new Error("No closing quotation"); word += s.slice(i + 1, end); i = end + 1; }
    else if (c === '"') {
      i++;
      for (;;) {
        if (i >= s.length) throw new Error("No closing quotation");
        if (s[i] === '"') { i++; break; }
        if (s[i] === "\\") {
          if (i + 1 >= s.length) throw new Error("No closing quotation");
          if (s[i + 1] === '"' || s[i + 1] === "\\") { word += s[i + 1]; i += 2; } else { word += "\\" + s[i + 1]; i += 2; }
        } else word += s[i++];
      }
    } else { word += c; i++; }
  }
  if (word !== null) out.push(word);
  return out;
}

// shlex.join: a word with nothing but letters, digits and _ @ % + = : , . / - is left as it is, any other is quoted
export const shellQuote = (w) => (w === "" ? "''" : /^[A-Za-z0-9_@%+=:,./-]+$/.test(w) ? w : `'${w.replace(/'/g, `'"'"'`)}'`);
export const shellJoin = (argv) => argv.map(shellQuote).join(" ");

// ---- an answer as the judge compares it: line ends as \n, trailing spaces and the blank lines at both ends dropped --------------
export const normOutput = (text) => String(text).replace(/\r\n/g, "\n").replace(/^\n+|\n+$/g, "").split("\n").map((l) => l.replace(/\s+$/u, "")).join("\n");

// Characters the judge and this page could read differently (control and format characters, line and paragraph
// separators) are not accepted in an input or an answer: tab and the line end of an answer are the exceptions.
const ODD = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u;
const odd = (text, allowed) => [...String(text)].some((ch) => ODD.test(ch) && !allowed.includes(ch));

// ---- the bundle: blackbox.py, cases.json and README.md, as accept.bundle writes them -------------------------------------
const JUDGE = (issue) => `"""Black-box acceptance for issue ${issue}, made by \`knos accept init\`. Read README.md.

This file runs as the judge, outside the pull request's tree, and never loads the pull request's code. It runs
"$KNOS_RUN <command>" (which runs the command in the pull request's tree, inside the sandbox) on every input in
cases.json, and compares what it prints with the answer recorded from the reference. Exit 0 means every case agrees."""
import json
import os
import subprocess
import sys
from pathlib import Path

SPEC = json.loads((Path(__file__).resolve().parent / "cases.json").read_text(encoding="utf-8"))
SECONDS = 60


def norm(text):
    return "\\n".join(line.rstrip() for line in text.replace("\\r\\n", "\\n").strip("\\n").split("\\n"))


def ask(argv, stdin):
    got = subprocess.run([os.environ["KNOS_RUN"], *argv], input=stdin, capture_output=True, timeout=SECONDS)
    return got.returncode, got.stdout, got.stderr


def check(ask=ask):
    """None when every case agrees, else one sentence about the first that does not."""
    for n, case in enumerate(SPEC["cases"], 1):
        at = "case %d, the input %s" % (n, repr(case["input"][:60]))
        try:
            code, out, err = ask(SPEC["run"], (case["input"] + "\\n").encode("utf-8"))
        except subprocess.TimeoutExpired:
            return "%s: the command took more than %d seconds" % (at, SECONDS)
        if code != 0:
            return "%s: the command exited %d: %s" % (at, code, " ".join(err.decode("utf-8", "replace").split())[-200:] or "it said nothing")
        got = norm(out.decode("utf-8", "replace"))
        if got != case["output"]:
            return "%s: it printed %s, expected %s" % (at, repr(got[:80]), repr(case["output"][:80]))
    return None


if __name__ == "__main__":
    why = check()
    if why:
        sys.exit(why)
    print("all %d cases agree" % len(SPEC["cases"]))
`;

const README = (issue, n, run) => `# Acceptance checks for issue ${issue}

Made by \`knos accept init\` from a reference implementation: ${n} inputs (given, seed none) and the answer the reference
gave to each, in \`cases.json\`. \`blackbox.py\` is the judge. It runs \`${run}\` in the pull request's tree for every input,
with the input on standard input, and compares what it prints with the recorded answer (trailing spaces and blank lines at
the end are ignored). Exit 0 means every case agrees.

It is black-box: the pull request's code runs as a separate process, and the judge never loads it, so nothing that code
does can change the verdict except printing the right answer. That is what lets Knos pay on this check alone, without a
merge, when this folder is on the default branch before the bounty is funded: \`/knos fund <amount>\` on issue ${issue}.

What it does not do: the cases are in this repository, so an implementation can answer exactly them from a table. More
cases make that more work, not impossible. A check that generates its inputs when it runs and compares them with a
reference at that time cannot be answered from a table: write that as \`blackbox.py\` yourself if the bounty is worth it
(Knos's docs/TAMPER.md measures the difference).
`;

// Python's json.dumps(spec, indent=1): one space of indent and every character past ~ written as a \\uXXXX escape
const pythonJson = (value) => JSON.stringify(value, null, 1).replace(/[^\n -~]/g, (ch) => `\\u${ch.charCodeAt(0).toString(16).padStart(4, "0")}`);

// The three files of `.knos/acceptance/<issue>/`, as text. `argv`: the command, already split; `cases`: [{ input, output }] with the
// answers already normalised (normOutput).
export function bundleFiles(issue, argv, cases) {
  const text = `${pythonJson({ v: 1, issue, run: argv, input: "given", seed: null, cases })}\n`;
  if (text.includes("KNOS_TREE")) throw new Error("an input or an answer holds the text KNOS_TREE, which a black-box bundle may not name.");
  return { "blackbox.py": JUDGE(issue), "cases.json": text, "README.md": README(issue, cases.length, shellJoin(argv)) };
}

// ---- the form ------------------------------------------------------------------------------------------------------------
const LOGIN = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/;
const REPO = /^(?![.]{1,2}$)[\w.-]{1,100}$/;

// "20", "7.5": digits with at most six decimals, in millionths; null for anything else
export function unitsOf(text) {
  const m = /^(\d{1,9})(?:\.(\d{1,6}))?$/.exec(String(text).trim());
  return m ? Number(m[1]) * 1_000_000 + Number((m[2] || "").padEnd(6, "0") || 0) : null;
}
export const amountWords = (units) => `${Math.trunc(units / 1_000_000)}${units % 1_000_000 ? `.${String(units % 1_000_000).padStart(6, "0").replace(/0+$/, "")}` : ""}`;

// What the person typed, as a task, or the first thing wrong with it as a sentence: { task } or { error }.
// `limits`: { min, max } of the amount, in millionths: a work order's, which is what `/knos fund` opens (5 to 100,000 on
// devnet). `limits.job`, when given, is { min, max } of the older kind of bounty (a 2.0 job: from 1), which keeps its own
// limits where the escrow holds no work orders yet; the refusal then names each kind's bound.
const said = (units) => amountWords(units).replace(/^\d+/, (whole) => Number(whole).toLocaleString("en-US"));
export const boundsWords = (limits) => `A work order holds from ${said(limits.min)} to ${said(limits.max)} test USDC, and \`/knos fund\` opens a work order.`
  + (limits.job ? ` A bounty of the older kind (2.0) takes from ${said(limits.job.min)} to ${said(limits.job.max)}, where the escrow holds no work orders yet; this page writes the comment for a work order.` : "");
export function check({ title, description, amount, command, login, repo, pairs }, limits) {
  const bad = (error) => ({ error });
  title = String(title ?? "").trim();
  if (!title) return bad("Give the task a title.");
  if ([...title].length > 200) return bad("The title is 200 characters at most.");
  if (/[\r\n]/.test(title)) return bad("The title is one line.");
  description = String(description ?? "").trim();
  if (!description) return bad("Describe the task: what a solution must do, in words, for the person who will read the issue.");
  if ([...description].length > 20000) return bad("The description is 20,000 characters at most.");
  const units = unitsOf(amount);
  if (units === null) return bad("The amount is a number like 20 or 7.5, with at most six decimals.");
  if (units < limits.min || units > limits.max) return bad(`The amount is from ${said(limits.min)} to ${said(limits.max)} test USDC. ${boundsWords(limits)}`);
  let argv;
  try { argv = shellSplit(String(command ?? "")); } catch (e) { return bad(`The command is not a command line (${e.message.toLowerCase()}). Write it as you would in a terminal, like python3 solution.py.`); }
  if (!argv.length) return bad("Name the command a solution is run as, like python3 solution.py. It reads one line on standard input and prints the answer.");
  login = String(login ?? "").trim().replace(/^@/, "");
  if (!LOGIN.test(login)) return bad("Your GitHub login is letters, digits and single hyphens, up to 39.");
  repo = String(repo ?? "").trim();
  if (!REPO.test(repo) || repo.endsWith(".git")) return bad("The repository's name is letters, digits, dots, hyphens and underscores, like knos-task.");
  const given = (pairs || []).filter((p) => String(p.input ?? "") !== "" || String(p.output ?? "").trim() !== "");
  if (given.length < MIN_PAIRS) return bad(`Give at least ${MIN_PAIRS} pairs of an input and its answer: fewer is too easy to answer from a table. ${given.length ? `${given.length} ${given.length === 1 ? "is" : "are"} filled in.` : "None is filled in."}`);
  if (given.length > MAX_PAIRS) return bad(`At most ${MAX_PAIRS} pairs: each is one run of the command in the judge's sandbox.`);
  const cases = [], seen = new Map();
  for (const [n, p] of given.entries()) {
    const input = String(p.input ?? ""), at = `Pair ${n + 1}`;
    if (input === "") return bad(`${at} has no input. An input is one line, and may be a single space but not nothing.`);
    if (/[\r\n]/.test(input)) return bad(`${at}: an input is one line.`);
    if ([...input].length > MAX_INPUT) return bad(`${at}: an input is ${MAX_INPUT} characters at most.`);
    if (odd(input, ["\t"]) || odd(p.output ?? "", ["\t", "\n", "\r"])) return bad(`${at} holds a control character, which the judge and this page might read differently. Use text with tabs, spaces and line ends only.`);
    if (seen.has(input)) return bad(`${at} has the same input as pair ${seen.get(input)}: one input has one answer.`);
    seen.set(input, n + 1);
    cases.push({ input, output: normOutput(p.output ?? "") });
  }
  if (!cases.some((c) => c.output)) return bad("Every answer is empty: there is nothing to compare.");
  if (cases.every((c) => c.output === normOutput(c.input))) return bad("A command that only prints its input back would pass these pairs: the inputs do not tell a right answer from an echo. Change some answers or inputs.");
  if (JSON.stringify(cases).includes("KNOS_TREE") || title.includes("KNOS_TREE")) return bad("An input or an answer holds the text KNOS_TREE, which a black-box bundle may not name.");
  return { task: { title, description, units, argv, login, repo, cases } };
}

// ---- the links ---------------------------------------------------------------------------------------------------------------
const q = encodeURIComponent;
export const repoLink = (repo) => `https://github.com/new?template_owner=${TEMPLATE.split("/")[0]}&template_name=${TEMPLATE.split("/")[1]}&name=${q(repo)}&visibility=public&owner=@me`;
export const issueLink = (login, repo, title, body) => `https://github.com/${login}/${repo}/issues/new?title=${q(title)}&body=${q(body)}`;
export const issueAddress = (login, repo, n) => `https://github.com/${login}/${repo}/issues/${n}`;
// A new file on the default branch: with its text in the link when that is short enough to carry, else an empty page to paste it into
export function fileLink(login, repo, branch, path, text) {
  const base = `https://github.com/${login}/${repo}/new/${q(branch)}?filename=${q(path)}`;
  const full = `${base}&value=${q(text)}`;
  return full.length <= MAX_URL ? { href: full, filled: true } : { href: base, filled: false };
}

// The issue's text: the description, then how it is accepted, in the words the judge will use
export function issueBody(task) {
  return `${task.description}

## How this is accepted

A solution is run as \`${shellJoin(task.argv)}\` in your pull request's tree. For each of the ${task.cases.length} recorded cases it is given one line on standard input and must print the recorded answer (trailing spaces and blank lines at the end are ignored). The cases are in the folder \`.knos/acceptance/\` named for this issue's number, on the default branch; the check runs your code as a separate process and compares only what it prints.

To take the bounty, open a pull request whose description says \`Fixes #\` and this issue's number.
`;
}

export const fundComment = (task) => `/knos fund ${amountWords(task.units)}`;

// ---- the page --------------------------------------------------------------------------------------------------------------
export function initTask(ctx) {
  const { $, esc, knos, gh } = ctx;
  const pairs = $("task-pairs");
  const say2 = (el, html, kind = "") => { el.innerHTML = `<p class="status ${kind}">${html}</p>`; };
  const say = (html, kind = "") => say2($("task-result"), html, kind);
  let n = 0;
  const addPair = (input = "", output = "") => {
    n++;
    const row = document.createElement("div");
    row.className = "pair";
    row.innerHTML = `<label for="task-in-${n}">Input ${pairs.children.length + 1}, one line</label><input id="task-in-${n}" class="task-in" type="text" autocomplete="off" spellcheck="false">
      <label for="task-out-${n}">Its answer</label><textarea id="task-out-${n}" class="task-out" rows="2" spellcheck="false"></textarea>`;
    row.querySelector("input").value = input;
    row.querySelector("textarea").value = output;
    pairs.append(row);
  };
  for (let i = 0; i < MIN_PAIRS; i++) addPair();
  $("task-add").onclick = () => { if (pairs.children.length < MAX_PAIRS) addPair(); else say(`At most ${MAX_PAIRS} pairs.`, "bad"); };

  const read = () => ({
    title: $("task-title").value, description: $("task-description").value, amount: $("task-amount").value, command: $("task-command").value, login: $("task-login").value, repo: $("task-repo-name").value,
    pairs: [...pairs.children].map((r) => ({ input: r.querySelector("input").value, output: r.querySelector("textarea").value })),
  });
  const copyButton = (button, text) => { button.onclick = async () => { try { await navigator.clipboard.writeText(text); button.textContent = "Copied"; } catch { button.textContent = "Select it and copy by hand"; } }; };

  $("task-form").onsubmit = (ev) => {
    ev.preventDefault();
    // the second deployment's bounds, from the client: an order's, and beside them a 2.0 job's (knos.MIN_AMOUNT and MAX_AMOUNT are the first deployment's, 1 to 500)
    const v2 = knos.v2;
    const got = check(read(), { min: v2.ORDER_MIN_AMOUNT, max: v2.MAX_AMOUNT, job: { min: v2.MIN_AMOUNT, max: v2.MAX_AMOUNT } });
    if (got.error) { say(esc(got.error), "bad"); return; }
    const t = got.task, body = issueBody(t), comment = fundComment(t), where = `${t.login}/${t.repo}`;
    $("task-result").innerHTML = `<div id="task-made"><p class="status ok">Nothing has been sent. These are the steps, in order; each opens a GitHub page that is filled in, and you press its last button there.</p>
      <ol class="steps" id="task-steps">
        <li id="task-step-1"><strong>Make the repository.</strong>
          <a id="task-repo-link" class="button" href="${esc(repoLink(t.repo))}" target="_blank" rel="noopener">Create ${esc(where)} from the template ${esc(TEMPLATE)}</a>
          <span class="fine">GitHub opens its page with the name filled in; keep it public, in your own account, and press its green button.</span></li>
        <li id="task-step-2"><strong>Open the issue.</strong>
          <a id="task-issue-link" class="button" href="${esc(issueLink(t.login, t.repo, t.title, body))}" target="_blank" rel="noopener">Open the issue in ${esc(where)}</a>
          <span class="fine">The title and the text are filled in (below, to read first). Press “Submit new issue” yourself, then look at the end of its address: that number is the issue's.</span>
          <details><summary>The issue's text</summary><textarea id="task-issue-text" readonly rows="10" spellcheck="false">${esc(body)}</textarea></details></li>
        <li id="task-step-3"><strong>Put the checks in.</strong> Enter the issue's number and the page makes three links, one for each file of the checks.
          <label for="task-number">The issue's number</label><input id="task-number" type="text" inputmode="numeric" autocomplete="off" placeholder="1">
          <button type="button" id="task-files-go" class="ghost small">Make the file links</button>
          <div id="task-files" role="status" aria-live="polite"></div></li>
        <li id="task-step-4"><strong>Fund it.</strong> When the three files are on the default branch, comment this on the issue:
          <pre id="task-fund-comment">${esc(comment)}</pre>
          <button type="button" id="task-copy" class="ghost small">Copy the comment</button>
          <span class="fine">Do it after the files are committed: the checks on the default branch at that moment are the ones the bounty is funded with. It is paid from a Balance of yours
            (<a href="#money">Add money</a>), or fund the issue from a wallet with <a href="#anyissue">Fund any issue</a>. The amount is test USDC on Solana devnet.</span></li>
      </ol>
      <p class="fine">What this made is a black-box check: your command's code runs as a separate process and only what it prints is compared. This page did not run a reference, so nothing has checked that
        your answers agree with a real solution: <code>knos accept init</code> does that, and tries the bundle against a command that only echoes its input. The cases are in the repository, so a solution can answer exactly them from a table; more cases make that more work.</p></div>`;
    copyButton($("task-copy"), comment);

    $("task-files-go").onclick = async () => {
      const out = $("task-files"), number = $("task-number").value.trim();
      if (!/^[1-9]\d{0,8}$/.test(number)) { say2(out, "The issue's number is digits, like 1: the end of its address.", "bad"); return; }
      say2(out, "Reading GitHub for the repository's default branch…");
      try {
        const repo = await gh(`/repos/${t.login}/${t.repo}`);
        const branch = repo.default_branch || "main", files = bundleFiles(Number(number), t.argv, t.cases);
        const dir = `.knos/acceptance/${number}`;
        out.innerHTML = `<p class="fine" id="task-branch">${esc(where)} is public; its default branch is <code>${esc(branch)}</code>. Open each link, and press “Commit new file” on GitHub (to the default branch, not a new one).</p>
          <ul class="plain" id="task-file-list">${Object.entries(files).map(([name, text], i) => {
            const link = fileLink(t.login, t.repo, branch, `${dir}/${name}`, text);
            return `<li data-file="${esc(name)}"><a class="button quiet" href="${esc(link.href)}" target="_blank" rel="noopener">${link.filled ? "Create" : "Open the new-file page for"} ${esc(dir)}/${esc(name)}</a>
              ${link.filled ? "" : `<span class="fine">This file is too long to carry in a link: copy it from the box below and paste it into the page that opens.</span>`}
              <details><summary>${esc(name)}, to read first (${new TextEncoder().encode(text).length} bytes)</summary><textarea readonly rows="8" spellcheck="false" data-text="${esc(name)}">${esc(text)}</textarea></details></li>`;
          }).join("")}</ul>
          <p class="fine">The issue itself: <a href="${esc(issueAddress(t.login, t.repo, number))}" target="_blank" rel="noopener">${esc(where)}#${esc(number)}</a>.</p>`;
      } catch (e) { say2(out, e.message === "GitHub has no such public repository, issue or user." ? `GitHub has no public repository ${esc(where)} yet: do step 1 first.` : esc(e.message), "bad"); }
    };
  };
}
