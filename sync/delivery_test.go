package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// L57: a finding renders as a GitHub suggestion block holding the whole line as it should read.
func TestAFindingRendersAsASuggestionBlock(t *testing.T) {
	dir := repo(t)
	writeFile(t, dir, "docs/data/x.json", `{"rows": 12011}`)
	r := runCheck(dir, mustLoad(t, dir), nil, checkOptions{}).Entries[0]
	want := "```suggestion\nWe list 12,011 companies today.\n```\n"
	if got := suggestion(r.Places[0]); got != want {
		t.Fatalf("suggestion %q, want %q", got, want)
	}
	if md := noticeMarkdown(r); !strings.Contains(md, want) {
		t.Fatalf("the notice has no suggestion block:\n%s", md)
	}
}

// L57: with opt_in set, a file without the marker is skipped; without opt_in every file in scope is read.
func TestAFileWithoutTheOptInMarkerIsSkipped(t *testing.T) {
	dir := repo(t)
	writeFile(t, dir, "docs/on.md", "<!-- knos-sync: on -->\nWe run 314 servers.\n")
	writeFile(t, dir, "docs/off.md", "We run 271 servers.\n")
	c := mustLoad(t, dir)
	c.OptIn = true
	res, err := runScan(dir, c, nil, true)
	if err != nil {
		t.Fatal(err)
	}
	if res.Files != 1 || !hasCandidate(res.Candidates, KindCount, "314", 2) || hasCandidate(res.Candidates, KindCount, "271", 0) {
		t.Fatalf("opted in: %d files, %+v", res.Files, res.Candidates)
	}
	c.OptIn = false
	if res, err = runScan(dir, c, nil, true); err != nil || !hasCandidate(res.Candidates, KindCount, "271", 1) {
		t.Fatalf("without opt_in the file was not read (%v)", err)
	}
}

// L57: the pre-commit hook exits non-zero on a stale claim, whatever its kind, and the hook file runs it.
func TestTheHookExitsNonZeroOnAStaleClaim(t *testing.T) {
	dir := repo(t)
	if code := run([]string{"hook", "--root", dir}); code != 0 {
		t.Fatalf("a fresh repository gave %d", code)
	}
	writeFile(t, dir, "docs/data/x.json", `{"rows": 12011}`)
	if code := run([]string{"hook", "--root", dir}); code != 1 {
		t.Fatalf("a stale count that does not block gave %d, want 1", code)
	}
	script := readFile(t, ".", "pre-commit-hook")
	if !strings.HasPrefix(script, "#!/bin/sh\n") || !strings.Contains(script, "exec knos-sync hook") {
		t.Fatalf("sync/pre-commit-hook:\n%s", script)
	}
}

// L57: acted_on is set when the flagged line differs at merge, with no accept command.
func TestActedOnIsSetWhenTheFlaggedLineDiffersAtMerge(t *testing.T) {
	dir := repo(t)
	writeFile(t, dir, "docs/data/x.json", `{"rows": 12011}`)
	base := runCheck(dir, mustLoad(t, dir), nil, checkOptions{})
	writeFile(t, dir, "docs/a.md", "# A\n\nWe list 12,011 companies today.\n")
	head := runCheck(dir, mustLoad(t, dir), nil, checkOptions{})
	if got := actedOn(base, head); got[KindCount] != 1 || len(got) != 1 {
		t.Fatalf("acted on %v, want count: 1", got)
	}
	if got := actedOn(base, base); len(got) != 0 {
		t.Fatalf("a line that did not change was counted: %v", got)
	}
	reports := t.TempDir()
	for name, rep := range map[string]*Report{"base.json": base, "head.json": head} {
		b, err := encodeJSON(rep, "")
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(reports, name), b, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	code := run([]string{"report", "--base", filepath.Join(reports, "base.json"), "--head", filepath.Join(reports, "head.json"),
		"--record", "--root", dir})
	if code != 0 {
		t.Fatalf("report --record gave %d", code)
	}
	if n := mustLoad(t, dir).Kinds[KindCount].ActedOn; n != 1 {
		t.Fatalf("acted_on is %d, want 1", n)
	}
}
