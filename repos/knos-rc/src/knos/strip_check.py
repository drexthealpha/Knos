"""The workflow-strip hole, read from GitHub: can the buyer remove the Knos workflow before merging?

A buyer who controls a repository can delete or edit the Knos workflow in the merging pull request itself, so the
check that would have refused the work never runs. What closes it is GitHub's, not Knos's:

    closed   a ruleset requires the Knos workflow (a `workflows` rule: "Require workflows to pass before merging").
             The workflow runs from the file the rule pins, not the pull request's copy. Only an organization or
             enterprise ruleset on GitHub Enterprise Cloud can carry that rule: a personal repository, or an
             organization on another plan, cannot (GitHub answers HTTP 422 "Invalid rule 'workflows'"). Closed only for
             people who cannot edit or bypass that ruleset: an organization owner (for an organization ruleset) or a
             repository admin (for a repository one) can still remove it.
    partly   a required status check names a Knos check (rulesets or classic branch protection). The merge waits for
             a check of that name, so removing the workflow alone blocks the merge. Still open: a pull request can change
             the workflow that produces the check, and an admin can remove the requirement. On a personal repository,
             or an organization without Enterprise Cloud, partly is the most GitHub allows.
    open     neither: nothing on GitHub stops the workflow being removed before the merge.

Source, read 2026-10-10: the rule is only in the Enterprise Cloud edition of GitHub's "Available rules for rulesets",
set "at the organization or enterprise level"; the Free, Pro and Team edition has no such rule:
https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-workflows-to-pass-before-merging

GitHub's API: GET /repos/{owner}/{repo}/rules/branches/{branch} (every active rule on the branch, from repository and
organization rulesets, each with `ruleset_source_type`), GET /repos/{owner}/{repo}/rulesets/{id} (its
`bypass_actors`, shown only to those with write access to the ruleset), GET /repos/{owner}/{repo}/branches/{branch}
(classic protection). Rule shapes: docs.github.com/en/rest/repos/rules. `knos protect --check-strip OWNER/REPO`."""
from __future__ import annotations

import re
import urllib.parse

WORKFLOW = re.compile(r"(?:^|/)\.github/workflows/(?:knos[\w.-]*|prove|fund|attest|claims)\.ya?ml$")
STATES = ("closed", "partly", "open")
DOCS = "https://docs.github.com/en/rest/repos/rules"
# said with every PARTLY: what it still leaves open, and why a personal repository cannot do better
STILL_OPEN = "a pull request can change the workflow that runs that check, and an admin can remove the requirement"
MOST = ("on a personal repository, or an organization without GitHub Enterprise Cloud, PARTLY is the most GitHub allows: "
        "only an organization or enterprise ruleset on Enterprise Cloud can require the workflow itself")


def knos_check(name) -> bool:
    """A status check Knos's workflows report (knos.terms names them the same way)."""
    from .terms import _knos_name
    return _knos_name(name)


def classify(rules: list | None, classic: dict | None = None, bypass: dict[int, list] | None = None) -> dict:
    """{state, says, evidence} from the branch's active rules (the rules/branches answer), its classic protection (the
    branches/{branch} answer's `protection`) and, when read, each ruleset's bypass actors (ruleset id -> list). `rules`
    None: GitHub could not be read, which is not the same as no rule."""
    if rules is None:
        return {"state": "unknown", "says": "GitHub's rules for the branch could not be read: nothing is claimed", "evidence": []}
    need, checks = [], []
    for r in rules:
        if not isinstance(r, dict):
            continue
        p = r.get("parameters") or {}
        if r.get("type") == "workflows":
            for w in p.get("workflows") or []:
                if isinstance(w, dict) and WORKFLOW.search(str(w.get("path") or "")):
                    need.append({"ruleset": r.get("ruleset_id"), "source": r.get("ruleset_source_type") or "Repository", "path": w["path"],
                                 "pinned": w.get("sha") or w.get("ref") or "", "repository_id": w.get("repository_id")})
        elif r.get("type") == "required_status_checks":
            checks += [{"source": f"ruleset {r.get('ruleset_id')}", "context": c.get("context")} for c in p.get("required_status_checks") or []
                       if isinstance(c, dict) and knos_check(c.get("context"))]
    rsc = (classic or {}).get("required_status_checks") or {}
    if rsc.get("enforcement_level") != "off":
        names = [c.get("context") for c in rsc.get("checks") or [] if isinstance(c, dict)] + list(rsc.get("contexts") or [])
        checks += [{"source": "classic branch protection", "context": n} for n in dict.fromkeys(names) if knos_check(n)]
    if need:
        who = sorted({"organization owners" if n["source"] == "Organization" else "repository admins" for n in need})
        by = [a for n in need for a in (bypass or {}).get(n["ruleset"], [])]
        return {"state": "closed", "evidence": need + checks,
                "says": (f"a ruleset requires the Knos workflow ({need[0]['path']}): a pull request cannot remove it. Not closed for "
                         f"{' and '.join(who)}, who can edit the ruleset" + (f", or for its {len(by)} bypass actor(s)" if by else "")
                         + ("" if bypass is not None else "; its bypass list was not read"))}
    if checks:
        return {"state": "partly", "evidence": checks,
                "says": (f"a required check names a Knos check ({checks[0]['context']}): the merge waits for it, so removing the workflow "
                         f"alone blocks the merge. Still open: {STILL_OPEN}. {MOST[0].upper()}{MOST[1:]}")}
    return {"state": "open", "evidence": [],
            "says": ("no ruleset requires the Knos workflow and no required check names it: the buyer can remove the workflow before merging. "
                     "A ruleset that requires a Knos check makes it PARTLY")}


def check(repo: str, get, branch: str | None = None) -> dict:
    """`classify` of `repo`'s default branch (or `branch`), read through `get(path)` (knos.judge.github)."""
    from .terms import pages
    try:
        branch = branch or (get(f"repos/{repo}") or {}).get("default_branch") or "main"
    except OSError:
        return classify(None)
    b = urllib.parse.quote(str(branch), safe="")
    rules = pages(f"repos/{repo}/rules/branches/{b}", get)
    try:
        classic = (get(f"repos/{repo}/branches/{b}") or {}).get("protection") or {}
    except OSError:
        classic = {}
    seen: dict[int, list] = {}
    shown = True
    for rid in sorted({r["ruleset_id"] for r in rules or [] if isinstance(r, dict) and r.get("type") == "workflows" and isinstance(r.get("ruleset_id"), int)}):
        try:
            got = get(f"repos/{repo}/rulesets/{rid}") or {}
        except OSError:
            got = {}
        if "bypass_actors" not in got:
            shown = False           # shown only to those with write access to the ruleset
            break
        seen[rid] = got["bypass_actors"] or []
    bypass = seen if shown else None
    return {"repository": repo, "branch": branch, **classify(rules, classic, bypass)}


def register(app, help_lines: list | None = None) -> None:
    """`knos protect --check-strip OWNER/REPO`, on the main app."""
    import importlib
    typer = importlib.import_module("typer")       # named here and not imported: this module is standard library only at import
    if help_lines is not None:
        help_lines.append(("protect", "For money", "Whether GitHub stops a buyer removing the Knos workflow before merging: closed, partly or open."))

    @app.command("protect")
    def protect_(check_strip: str = typer.Option(..., "--check-strip", metavar="OWNER/REPO", help="the repository to read"),
                 branch: str = typer.Option("", "--branch", help="the branch (default: the repository's default branch)")) -> None:
        """Read the repository's rulesets and branch protection and say whether a pull request can pass by deleting the
        Knos workflow. CLOSED: a ruleset requires the Knos workflow. PARTLY: only a required status check.
        OPEN: neither. Anyone who can edit the ruleset can always reopen it. On a personal repository, PARTLY
        is the most GitHub allows. Exit code 1 when open."""
        from .judge import github
        got = check(check_strip, github, branch or None)
        typer.echo(f"{got['repository']} {got['branch']}: {got['state'].upper()}. {got['says'][0].upper()}{got['says'][1:]}.")
        if got["state"] in ("open", "unknown"):
            raise typer.Exit(1)
