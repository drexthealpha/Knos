package main

import (
	"crypto/sha256"
	"encoding/hex"
	"runtime"
	"testing"
)

func openTestState(t *testing.T, dir string) *State {
	t.Helper()
	st, err := openState(dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { st.Close() })
	return st
}

// twoEntries is repo with a second entry, in its own doc, read from its own data file.
func twoEntries(t *testing.T) string {
	t.Helper()
	dir := repo(t)
	writeFile(t, dir, "docs/b.md", "There are 42 stars here.\n")
	writeFile(t, dir, "docs/data/y.json", `{"stars": 42}`)
	c := fixture()
	c.Entries = append(c.Entries, Entry{ID: "stars", Kind: KindCount, Subject: "stars",
		Places:  []Place{{File: "docs/b.md", Line: 1, Text: "42 stars here.", Says: "42"}},
		Command: []string{"json", "docs/data/y.json", "stars"}, Expected: "42", Comparator: "equal"})
	writeFactsFile(t, dir, c)
	return dir
}

// L56: after one file changes, check runs again only the entries whose input hashes changed, and prints the count.
func TestCheckRerunsOnlyEntriesWhoseInputsChanged(t *testing.T) {
	dir := twoEntries(t)
	st := openTestState(t, dir)
	c := mustLoad(t, dir)
	if rep := runCheck(dir, c, st, checkOptions{}); rep.Rechecked != 2 || rep.Reused != 0 {
		t.Fatalf("first check: %d rechecked, %d reused", rep.Rechecked, rep.Reused)
	}
	if rep := runCheck(dir, c, st, checkOptions{}); rep.Rechecked != 0 || rep.Reused != 2 || rep.Verified != 2 {
		t.Fatalf("nothing changed: %d rechecked, %d reused, %d verified", rep.Rechecked, rep.Reused, rep.Verified)
	}
	writeFile(t, dir, "docs/data/y.json", `{"stars": 43}`)
	rep := runCheck(dir, c, st, checkOptions{})
	if rep.Rechecked != 1 || rep.Reused != 1 {
		t.Fatalf("one input changed: %d rechecked, %d reused", rep.Rechecked, rep.Reused)
	}
	if got := recheckLine(rep); got != "rechecked: 1 of 2 entries; 1 reused, their inputs unchanged" {
		t.Fatalf("printed %q", got)
	}
	for _, r := range rep.Entries {
		if want := map[string]string{"rows": StatusFresh, "stars": StatusStale}[r.ID]; r.Status != want {
			t.Fatalf("%s is %s, want %s", r.ID, r.Status, want)
		}
	}
	if rep := runCheck(dir, c, st, checkOptions{full: true}); rep.Rechecked != 2 {
		t.Fatalf("--full ran %d entries again, want 2", rep.Rechecked)
	}
}

// L56: nodes and edges tables, indexes on both edge directions, a confidence and a source tag on every edge, and hop
// distances on what a change reaches.
func TestTheGraphHasEdgesBothWaysWithConfidenceAndSource(t *testing.T) {
	dir := twoEntries(t)
	st := openTestState(t, dir)
	runCheck(dir, mustLoad(t, dir), st, checkOptions{})
	for name, first := range map[string]string{"edges_src": "src", "edges_dst": "dst"} {
		var col string
		if err := st.db.QueryRow(`SELECT name FROM pragma_index_info('` + name + `') WHERE seqno = 0`).Scan(&col); err != nil || col != first {
			t.Fatalf("index %s starts with %q (%v), want %s", name, col, err, first)
		}
	}
	var n, bad int
	if err := st.db.QueryRow(`SELECT COUNT(*) FROM edges`).Scan(&n); err != nil || n != 4 {
		t.Fatalf("%d edges (%v), want 4: two entries, each with its doc and its data file", n, err)
	}
	if err := st.db.QueryRow(`SELECT COUNT(*) FROM edges WHERE confidence <= 0 OR confidence > 1 OR source NOT IN ('facts', 'static')`).Scan(&bad); err != nil || bad != 0 {
		t.Fatalf("%d edges without a confidence or a source tag (%v)", bad, err)
	}
	got, err := st.affected([]string{"docs/data/y.json"}, 10)
	if err != nil {
		t.Fatal(err)
	}
	want := []Affected{{NodeEntry, "stars", 1}, {NodeFile, "docs/b.md", 2}}
	if len(got) != len(want) || got[0] != want[0] || got[1] != want[1] {
		t.Fatalf("affected %+v, want %+v", got, want)
	}
}

// L56: a file's content is kept once, as a compressed blob, and given back whole.
func TestScanKeepsEachFileOnceAsACompressedBlob(t *testing.T) {
	dir := repo(t)
	st := openTestState(t, dir)
	if _, err := runScan(dir, mustLoad(t, dir), st, false); err != nil {
		t.Fatal(err)
	}
	content := readFile(t, dir, "docs/a.md")
	sum := sha256.Sum256([]byte(content))
	got, err := st.blob(hex.EncodeToString(sum[:]))
	if err != nil || string(got) != content {
		t.Fatalf("blob %q (%v), want %q", got, err, content)
	}
	var span string
	if err := st.db.QueryRow(`SELECT blob FROM nodes WHERE kind = 'file' AND key = 'docs/a.md'`).Scan(&span); err != nil || span != hex.EncodeToString(sum[:]) {
		t.Fatalf("the file node points at blob %q (%v)", span, err)
	}
}

// L56: scan reads its peak memory on Windows, Linux and Mac, prints it beside its cap, and exits 1 past the cap.
func TestScanReadsItsPeakMemoryAndKeepsItsCap(t *testing.T) {
	dir := repo(t)
	if code := run([]string{"scan", "--root", dir, "--mem-cap-mib", "2048"}); code != 0 {
		t.Fatalf("scan under a 2048 MiB cap gave %d", code)
	}
	peak := peakMemory()
	switch runtime.GOOS {
	case "linux", "darwin", "windows":
		if peak == 0 {
			t.Fatalf("the peak memory was not read on %s", runtime.GOOS)
		}
	}
	if line, over := memoryLine(peak, 2048); over {
		t.Fatalf("over the cap: %s", line)
	}
	if line, over := memoryLine(3<<30, 2048); !over || line != "peak memory: 3072 MiB of a 2048 MiB cap" {
		t.Fatalf("3 GiB against a 2048 MiB cap: %q %v", line, over)
	}
	if code := run([]string{"scan", "--root", dir, "--mem-cap-mib", "1"}); code != 1 {
		t.Fatalf("scan past a 1 MiB cap gave %d, want 1", code)
	}
}
