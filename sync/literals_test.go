package main

import (
	"strings"
	"testing"
	"time"
)

// L55: a constant in a .py file whose value README.md states becomes a claim, with a command that reads it back.
func TestAConstantInCodeThatTheReadmeStatesBecomesAClaim(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "src/limits.py", "MAX_RUNS = 37\nOTHER = 5\n")
	writeFile(t, dir, "README.md", "# Tool\n\nEach key gets 37 runs a day.\n")
	claims, err := literalClaims(dir, defaultFacts())
	if err != nil {
		t.Fatal(err)
	}
	if len(claims) != 1 {
		t.Fatalf("want one claim, got %+v", claims)
	}
	lc := claims[0]
	if lc.Const.Name != "MAX_RUNS" || lc.Const.File != "src/limits.py" || lc.Doc.File != "README.md" || lc.Doc.Line != 3 ||
		lc.Doc.Value != "37" || lc.Confidence != 1 {
		t.Fatalf("claim %+v", lc)
	}
	if got, err := runCommand(dir, lc.Command, false, time.Second); err != nil || got != "37" {
		t.Fatalf("the claim's command gave %q (%v), want 37", got, err)
	}
	if !strings.HasPrefix(lc.linkCommand(), "knos-sync link --id max-runs --kind count ") {
		t.Fatalf("link command %q", lc.linkCommand())
	}
}

// L55: check sorts its notices by a rank it prints; a confirmed stale fact comes before an unconfirmed one.
func TestCheckOutputIsSortedByAPrintedRank(t *testing.T) {
	dir := twoEntries(t)
	c := mustLoad(t, dir)
	c.Entries[1].ConfirmedByPerson = true
	writeFactsFile(t, dir, c)
	writeFile(t, dir, "docs/data/x.json", `{"rows": 12011}`)
	writeFile(t, dir, "docs/data/y.json", `{"stars": 43}`)
	rep := runCheck(dir, mustLoad(t, dir), nil, checkOptions{})
	if rep.Entries[0].ID != "stars" || rep.Entries[0].Rank != 1 || rep.Entries[1].ID != "rows" || rep.Entries[1].Rank != 2 {
		t.Fatalf("order %s #%d, %s #%d", rep.Entries[0].ID, rep.Entries[0].Rank, rep.Entries[1].ID, rep.Entries[1].Rank)
	}
	if rep.Entries[0].Score <= rep.Entries[1].Score {
		t.Fatalf("scores %d and %d", rep.Entries[0].Score, rep.Entries[1].Score)
	}
	if s := noticeText(rep.Entries[0]); !strings.HasPrefix(s, "#1 STALE stars") {
		t.Fatalf("printed %q", s)
	}
	if s := noticeMarkdown(rep.Entries[1]); !strings.HasPrefix(s, "#2 **rows**") {
		t.Fatalf("printed %q", s)
	}
}

// L55: the coverage report lists public functions that no doc mentions, and leaves out private ones and tests.
func TestCoverageListsPublicFunctionsNoDocMentions(t *testing.T) {
	dir := repo(t)
	writeFile(t, dir, "src/tool.py", "def documented():\n    pass\n\n\ndef forgotten():\n    pass\n\n\ndef _private():\n    pass\n")
	writeFile(t, dir, "tests/test_tool.py", "def test_forgotten():\n    pass\n")
	writeFile(t, dir, "docs/tool.md", "Call documented() to start.\n")
	missing, total, err := uncovered(dir, mustLoad(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	if total != 2 || len(missing) != 1 || missing[0].Name != "forgotten" || missing[0].File != "src/tool.py" || missing[0].Line != 5 {
		t.Fatalf("%d public, missing %+v", total, missing)
	}
}
