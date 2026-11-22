package main

import (
	"os/exec"
	"testing"
)

// gitT runs git in dir as a test author; a test repository never signs.
func gitT(t *testing.T, dir string, args ...string) {
	t.Helper()
	base := []string{"-C", dir, "-c", "user.name=knos-sync test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false"}
	if out, err := exec.Command("git", append(base, args...)...).CombinedOutput(); err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
}

func gitInit(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	gitT(t, dir, "init", "-q")
	return dir
}

func commitAll(t *testing.T, dir, msg string) {
	t.Helper()
	gitT(t, dir, "add", "-A")
	gitT(t, dir, "commit", "-q", "-m", msg)
}

// L54: a function renamed in git history is reported with its new name; a name that never resolved is not reported.
func TestANameRenamedInHistoryIsReportedWithItsNewName(t *testing.T) {
	dir := gitInit(t)
	writeFile(t, dir, "tools/calc.py", "def old_total(rows):\n    return sum(rows)\n")
	writeFile(t, dir, "docs/guide.md", "# Guide\n\nCall `old_total()` to add the rows.\n\nCall `never_written()` too.\n")
	commitAll(t, dir, "first")
	writeFile(t, dir, "tools/calc.py", "def new_total(rows):\n    return sum(rows)\n")
	commitAll(t, dir, "rename")
	found, err := checkNames(dir, defaultFacts(), nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(found) != 1 {
		t.Fatalf("want only old_total, found %+v", found)
	}
	f := found[0]
	if f.Name != "old_total" || f.Line != 3 || f.Status != NameRenamed || f.NewName != "new_total" {
		t.Fatalf("found %+v", f)
	}
	if got := nameText(f); got != "NAME docs/guide.md:3  old_total() was renamed to new_total\n" {
		t.Fatalf("printed %q", got)
	}
}

// L54: a path tells renamed from removed; a path that never existed is not reported on a committed line, and is
// reported on a line not committed yet.
func TestAPathTellsRenamedFromRemoved(t *testing.T) {
	dir := gitInit(t)
	writeFile(t, dir, "docs/data/a.json", `{"a": 1}`+"\n")
	writeFile(t, dir, "docs/data/b.json", `{"b": 2}`+"\n")
	writeFile(t, dir, "docs/guide.md", "Read docs/data/a.json first.\n\nThen docs/data/b.json.\n\nNot docs/data/planned.json yet.\n")
	commitAll(t, dir, "first")
	gitT(t, dir, "mv", "docs/data/a.json", "docs/data/c.json")
	gitT(t, dir, "rm", "-q", "docs/data/b.json")
	commitAll(t, dir, "move and remove")
	writeFile(t, dir, "docs/guide.md", readFile(t, dir, "docs/guide.md")+"\nSee docs/data/missing.json.\n")
	found, err := checkNames(dir, defaultFacts(), nil)
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]string{}
	for _, f := range found {
		got[f.Name] = f.Status + " " + f.NewName
	}
	want := map[string]string{
		"docs/data/a.json":       NameRenamed + " docs/data/c.json",
		"docs/data/b.json":       NameRemoved + " ",
		"docs/data/missing.json": NameNew + " ",
	}
	if len(got) != len(want) {
		t.Fatalf("found %v, want %v", got, want)
	}
	for k, v := range want {
		if got[k] != v {
			t.Fatalf("%s: %q, want %q (all: %v)", k, got[k], v, got)
		}
	}
}

// L54: check reports names only when the name kind is on.
func TestCheckReportsNamesOnlyWhenTheNameKindIsOn(t *testing.T) {
	dir := gitInit(t)
	writeFile(t, dir, "docs/a.md", "# A\n\nWe list 12,010 companies today.\n")
	writeFile(t, dir, "docs/data/x.json", `{"rows": 12010}`)
	c := fixture()
	writeFactsFile(t, dir, c)
	commitAll(t, dir, "first")
	writeFile(t, dir, "docs/a.md", "# A\n\nWe list 12,010 companies today.\n\nSee docs/data/gone.json.\n")
	if rep := runCheck(dir, mustLoad(t, dir), nil, checkOptions{}); len(rep.Names) != 0 {
		t.Fatalf("the name kind is off and names were reported: %+v", rep.Names)
	}
	c.Kinds[KindName].On = true
	writeFactsFile(t, dir, c)
	rep := runCheck(dir, mustLoad(t, dir), nil, checkOptions{})
	if len(rep.Names) != 1 || rep.Names[0].Name != "docs/data/gone.json" || rep.Names[0].Line != 5 || rep.Exit != 0 {
		t.Fatalf("names: %+v, exit %d", rep.Names, rep.Exit)
	}
}
