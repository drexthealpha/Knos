package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeFile(t *testing.T, dir, rel, content string) {
	t.Helper()
	p := filepath.Join(dir, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func readFile(t *testing.T, dir, rel string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(dir, filepath.FromSlash(rel)))
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func hasCandidate(cs []Candidate, kind, value string, line int) bool {
	for _, c := range cs {
		if c.Kind == kind && c.Value == value && (line == 0 || c.Line == line) {
			return true
		}
	}
	return false
}

func TestExtractFindsTheFiveKinds(t *testing.T) {
	text := "Knos v0.4.0 lists 826 repositories, costs $1 or 0.30%, see docs/NUMBERS.md and https://example.com/x. " +
		"Its hash is 7d074302abc, read on 16 Nov 2026, in 2026."
	cs := extractLine(lineText{Line: 4, Text: text})
	for _, want := range []struct{ kind, value string }{
		{KindVersion, "v0.4.0"}, {KindCount, "826"}, {KindPrice, "$1"}, {KindPrice, "0.30%"},
		{KindName, "docs/NUMBERS.md"}, {KindName, "https://example.com/x"}, {KindHash, "7d074302abc"},
	} {
		if !hasCandidate(cs, want.kind, want.value, 4) {
			t.Errorf("no %s %q in %+v", want.kind, want.value, cs)
		}
	}
	for _, c := range cs {
		if c.Value == "16" || c.Value == "2026" || c.Value == "0.30" {
			t.Errorf("a date or a decimal became a candidate: %+v", c)
		}
	}
}

func TestExtractLeavesWordsAfterNumbersThatAreNotThings(t *testing.T) {
	cs := extractLine(lineText{Line: 1, Text: "It took 12 ms and 3 of them failed."})
	if hasCandidate(cs, KindCount, "12", 1) || hasCandidate(cs, KindCount, "3", 1) {
		t.Errorf("a unit or a function word made a count: %+v", cs)
	}
	cs = extractLine(lineText{Line: 1, Text: "The tool supports every editor there is today."})
	if !hasCandidate(cs, KindSentence, "The tool supports every editor there is today.", 1) {
		t.Errorf("a factual sentence with no kind is not listed as not machine-checkable: %+v", cs)
	}
}

func TestMarkdownReadsProseAndSkipsCodeBlocks(t *testing.T) {
	src := "# Title\n\nWe track **826** repositories and run `knos check` daily.\n\n```go\n999 servers\n```\n\nSee [the list](docs/a.md).\n"
	var cs []Candidate
	for _, lt := range markdownLines([]byte(src)) {
		cs = append(cs, extractLine(lt)...)
	}
	if !hasCandidate(cs, KindCount, "826", 3) {
		t.Errorf("no count 826 on line 3: %+v", cs)
	}
	if !hasCandidate(cs, KindName, "knos check", 3) {
		t.Errorf("no command on line 3: %+v", cs)
	}
	if !hasCandidate(cs, KindName, "docs/a.md", 9) {
		t.Errorf("no link target on line 9: %+v", cs)
	}
	for _, c := range cs {
		if strings.Contains(c.Value, "999") {
			t.Errorf("a code block was read: %+v", c)
		}
	}
}

func TestHTMLReadsOnlyVisibleText(t *testing.T) {
	src := "<html><head><title>7 things</title></head>\n<body>\n<script>var x = \"123 apples\";</script>\n" +
		"<p>We have <b>12,010</b> companies</p>\n<code>knos-sync check</code>\n<a href=\"https://x.org/p\">link</a>\n</body></html>\n"
	var cs []Candidate
	for _, lt := range htmlLines([]byte(src)) {
		cs = append(cs, extractLine(lt)...)
	}
	if !hasCandidate(cs, KindCount, "12,010", 4) {
		t.Errorf("no count 12,010 on line 4: %+v", cs)
	}
	if !hasCandidate(cs, KindName, "knos-sync check", 5) {
		t.Errorf("no command on line 5: %+v", cs)
	}
	if !hasCandidate(cs, KindName, "https://x.org/p", 6) {
		t.Errorf("no link on line 6: %+v", cs)
	}
	for _, c := range cs {
		if c.Value == "7" || c.Value == "123" {
			t.Errorf("a script or the head was read: %+v", c)
		}
	}
}

func TestCompareAndFormatLikeTheText(t *testing.T) {
	cases := []struct {
		kind, cmp, stated, actual string
		want                      bool
	}{
		{KindCount, "equal", "12,010", "12010", true},
		{KindCount, "equal", "12,010", "12011", false},
		{KindCount, "at_least", "800", "826", true},
		{KindCount, "at_most", "800", "826", false},
		{KindCount, "approximately", "4,000", "4049", true},
		{KindPrice, "rounded", "17.8%", "17.83", true},
		{KindPrice, "equal", "$1", "1", true},
		{KindHash, "prefix", "7d074302", "7d074302abcdef", true},
		{KindVersion, "equal", "0.4.0", "0.4.1", false},
	}
	for _, c := range cases {
		got, err := compare(c.kind, c.cmp, c.stated, c.actual, 0)
		if err != nil || got != c.want {
			t.Errorf("compare(%s %s %q %q) = %v %v, want %v", c.kind, c.cmp, c.stated, c.actual, got, err, c.want)
		}
	}
	formats := []struct{ kind, says, actual, want string }{
		{KindCount, "12,010", "12011", "12,011"},
		{KindPrice, "$1", "2", "$2"},
		{KindPrice, "17.8%", "18.24", "18.2%"},
		{KindHash, "abcdef12", "1234567890abcdef", "12345678"},
		{KindVersion, "0.4.0", "0.4.1", "0.4.1"},
	}
	for _, f := range formats {
		if got := formatLike(f.kind, f.says, f.actual); got != f.want {
			t.Errorf("formatLike(%q, %q) = %q, want %q", f.says, f.actual, got, f.want)
		}
	}
}

func TestConvertAndJSONValue(t *testing.T) {
	if got, err := applyConvert("0.003", "mul:100"); err != nil || got != "0.3" {
		t.Errorf("mul:100 of 0.003 = %q %v", got, err)
	}
	if got, err := applyConvert("30", "div:100;round:2"); err != nil || got != "0.3" {
		t.Errorf("div:100;round:2 of 30 = %q %v", got, err)
	}
	if _, err := parseConvert("times:3"); err == nil {
		t.Error("an unknown conversion was accepted")
	}
	raw := []byte(`{"a":{"b":[1,{"c":"x"}]},"k/l":2.50}`)
	if v, err := jsonValue(raw, "a.b.1.c"); err != nil || v != "x" {
		t.Errorf("dotted path = %q %v", v, err)
	}
	if v, err := jsonValue(raw, "/k~1l"); err != nil || v != "2.50" {
		t.Errorf("pointer = %q %v", v, err)
	}
	if _, err := jsonValue(raw, "a"); err == nil {
		t.Error("an object was read as one value")
	}
}

func fixture() *Facts {
	c := defaultFacts()
	c.Note = "test"
	c.Skip, c.Historical = []string{}, []string{}
	c.Existing, c.Generated, c.Silenced = []Existing{}, []Generated{}, []Silence{}
	c.Entries = []Entry{{
		ID: "rows", Kind: KindCount, Subject: "rows of the list",
		Places:  []Place{{File: "docs/a.md", Line: 3, Text: "12,010 companies", Says: "12,010"}},
		Command: []string{"json", "docs/data/x.json", "rows"}, Expected: "12010", Comparator: "equal",
	}}
	return c
}

func writeFactsFile(t *testing.T, dir string, c *Facts) {
	t.Helper()
	b, err := encodeJSON(c, "")
	if err != nil {
		t.Fatal(err)
	}
	writeFile(t, dir, FactsPath, string(b)+"\n")
}

func repo(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	writeFile(t, dir, "docs/a.md", "# A\n\nWe list 12,010 companies today.\n")
	writeFile(t, dir, "docs/data/x.json", `{"rows": 12010}`)
	writeFactsFile(t, dir, fixture())
	return dir
}

func mustLoad(t *testing.T, dir string) *Facts {
	t.Helper()
	c, _, err := loadFacts(dir)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestCheckFindsStaleAndBlocksOnlyWhenOptedIn(t *testing.T) {
	dir := repo(t)
	rep := runCheck(dir, mustLoad(t, dir), nil, checkOptions{})
	if rep.Exit != 0 || rep.Entries[0].Status != StatusFresh || rep.Verified != 1 {
		t.Fatalf("fresh repository: %+v", rep)
	}
	writeFile(t, dir, "docs/data/x.json", `{"rows": 12011}`)
	rep = runCheck(dir, mustLoad(t, dir), nil, checkOptions{})
	r := rep.Entries[0]
	if r.Status != StatusStale || r.Places[0].Now != "12,010 companies" || r.Places[0].Should != "12,011 companies" || r.Places[0].Line != 3 {
		t.Fatalf("stale entry: %+v", r)
	}
	if code := run([]string{"check", "--root", dir}); code != 0 {
		t.Fatalf("a stale entry of a kind that does not block gave exit %d", code)
	}
	c := fixture()
	c.Kinds[KindCount].Block = true
	writeFactsFile(t, dir, c)
	if code := run([]string{"check", "--root", dir}); code != 0 {
		t.Fatalf("an unconfirmed entry gave exit %d", code)
	}
	c.Entries[0].ConfirmedByPerson = true
	writeFactsFile(t, dir, c)
	if code := run([]string{"check", "--root", dir}); code != 1 {
		t.Fatalf("a confirmed stale count of a blocking kind gave exit %d, want 1", code)
	}
	// a value from a chain never blocks
	writeFile(t, dir, "docs/data/finalized.json", `{"rows": 12011}`)
	c.Entries[0].Source, c.Entries[0].Command = "chain", []string{"json", "docs/data/finalized.json", "rows"}
	writeFile(t, dir, "docs/a.md", "# A\n\nWe list 12,010 companies today.\n")
	writeFactsFile(t, dir, c)
	rep = runCheck(dir, mustLoad(t, dir), nil, checkOptions{})
	if rep.Exit != 0 || !rep.Entries[0].Reread || rep.Entries[0].Blocking {
		t.Fatalf("a chain value: %+v", rep.Entries[0])
	}
}

func TestValidateKeepsTheLaw(t *testing.T) {
	c := fixture()
	c.Kinds[KindPrice].Block = true
	c.Kinds[KindName].Block = true
	if p := strings.Join(c.Validate(), "\n"); !strings.Contains(p, "kinds.price") || !strings.Contains(p, "kinds.name") {
		t.Errorf("a price or a name could block: %s", p)
	}
	c = fixture()
	c.Entries[0].Source = "chain"
	if p := strings.Join(c.Validate(), "\n"); !strings.Contains(p, "finalized") {
		t.Errorf("a chain value not read at finalized was accepted: %s", p)
	}
	c = fixture()
	c.Entries[0].Command = []string{"json", "docs/other.md", "rows"}
	if p := strings.Join(c.Validate(), "\n"); !strings.Contains(p, "cannot prove a document") {
		t.Errorf("a document proved a document: %s", p)
	}
	c = fixture()
	c.Entries[0].Places[0].File = "src/a.md"
	if len(c.Validate()) == 0 {
		t.Error("a place outside README.md, docs/ and web/ was accepted")
	}
}

func TestFixAcceptAndSilence(t *testing.T) {
	dir := repo(t)
	writeFile(t, dir, "docs/data/x.json", `{"rows": 12011}`)
	if code := run([]string{"fix", "--root", dir}); code != 0 {
		t.Fatalf("fix gave %d", code)
	}
	if got := readFile(t, dir, "docs/a.md"); got != "# A\n\nWe list 12,011 companies today.\n" {
		t.Fatalf("fix wrote %q", got)
	}
	c := mustLoad(t, dir)
	if c.Entries[0].Places[0].Says != "12,011" || c.Entries[0].Expected != "12011" || c.Kinds[KindCount].ActedOn != 1 {
		t.Fatalf("fix did not record the place: %+v %+v", c.Entries[0], c.Kinds[KindCount])
	}
	if r := runCheck(dir, c, nil, checkOptions{}).Entries[0]; r.Status != StatusFresh {
		t.Fatalf("after fix: %+v", r)
	}
	// the text moves and is changed by hand to the true value: accept records it
	writeFile(t, dir, "docs/data/x.json", `{"rows": 12012}`)
	writeFile(t, dir, "docs/a.md", "# A\n\nIntro.\n\nWe list 12,012 companies today.\n")
	if r := runCheck(dir, mustLoad(t, dir), nil, checkOptions{}).Entries[0]; r.Status != StatusRecord || r.Places[0].Line != 5 {
		t.Fatalf("a moved, corrected line: %+v", r)
	}
	if code := run([]string{"accept", "rows", "--root", dir}); code != 0 {
		t.Fatalf("accept gave %d", code)
	}
	c = mustLoad(t, dir)
	if p := c.Entries[0].Places[0]; p.Line != 5 || p.Says != "12,012" || p.Text != "12,012 companies" {
		t.Fatalf("accept recorded %+v", p)
	}
	// a notice marked not useful is counted, and past 10% of marks the kind's notices turn off
	writeFile(t, dir, "docs/data/x.json", `{"rows": 12013}`)
	if code := run([]string{"silence", "rows", "--root", dir}); code != 0 {
		t.Fatalf("silence gave %d", code)
	}
	c = mustLoad(t, dir)
	if len(c.Silenced) != 1 || c.Silenced[0].Says != "12,012" || c.Silenced[0].Reason != "not useful" || c.Kinds[KindCount].NotUseful != 1 {
		t.Fatalf("silence recorded %+v %+v", c.Silenced, c.Kinds[KindCount])
	}
	if r := runCheck(dir, c, nil, checkOptions{}).Entries[0]; r.Status != StatusOff {
		t.Fatalf("1 not useful of 3 marks is over 10%%, the kind should be off: %+v", r)
	}
	if code := run([]string{"confirm", "rows", "--root", dir}); code != 0 || !mustLoad(t, dir).Entries[0].ConfirmedByPerson {
		t.Fatalf("confirm gave %d", code)
	}
}

func TestLinkOnlyWhenTheCommandReproducesTheValue(t *testing.T) {
	dir := repo(t)
	writeFile(t, dir, "docs/b.md", "There are 42 stars here.\n")
	writeFile(t, dir, "docs/data/y.json", `{"stars": 41}`)
	args := []string{"link", "--root", dir, "--id", "stars", "--kind", "count", "--subject", "stars", "--place", "docs/b.md:1",
		"--says", "42", "--", "json", "docs/data/y.json", "stars"}
	if code := run(args); code != 1 {
		t.Fatalf("a link whose command gives 41 for 42 gave %d, want 1", code)
	}
	writeFile(t, dir, "docs/data/y.json", `{"stars": 42}`)
	if code := run(args); code != 0 {
		t.Fatalf("link gave %d", code)
	}
	e, _ := mustLoad(t, dir).entry("stars")
	if e == nil || e.Places[0].Text != "42 stars here." || e.Expected != "42" || e.ConfirmedByPerson {
		t.Fatalf("linked %+v", e)
	}
	// a value an existing check holds is not linked twice (E1)
	writeFile(t, dir, "docs/facts.json", `{"facts": [{"say": ["7"], "doc": "docs/c.md"}]}`)
	writeFile(t, dir, "docs/c.md", "We ran 7 drills.\n")
	writeFile(t, dir, "docs/data/z.json", `{"n": 7}`)
	c := mustLoad(t, dir)
	c.Existing = []Existing{{Name: "claims_check", Command: "python scripts/claims_check.py", RunBy: "tests.yml", Checks: "numbers", FactsFrom: "docs/facts.json"}}
	writeFactsFile(t, dir, c)
	code := run([]string{"link", "--root", dir, "--id", "drills", "--kind", "count", "--subject", "drills", "--place", "docs/c.md:1",
		"--says", "7", "--", "json", "docs/data/z.json", "n"})
	if code != 2 {
		t.Fatalf("a covered place gave %d, want 2", code)
	}
}

func TestChangeReportListsOnlyWhatTheChangeMadeStale(t *testing.T) {
	stale := EntryResult{ID: "rows", Kind: KindCount, Subject: "rows", Actual: "12011", Status: StatusStale,
		Places: []PlaceResult{{File: "docs/a.md", Line: 3, Stated: "12,010", Now: "12,010 companies", Should: "12,011 companies", Status: StatusStale}}}
	fresh := EntryResult{ID: "rows", Kind: KindCount, Status: StatusFresh, Actual: "12010",
		Places: []PlaceResult{{File: "docs/a.md", Line: 3, Stated: "12,010", Status: StatusFresh}}}
	text, made, _ := changeReport(&Report{Entries: []EntryResult{fresh}}, &Report{Entries: []EntryResult{stale}})
	if made != 1 || !strings.HasPrefix(text, "<!-- knos-sync -->") || !strings.Contains(text, "`12,011 companies`") {
		t.Fatalf("the comment: %d %q", made, text)
	}
	if text, made, _ = changeReport(&Report{Entries: []EntryResult{stale}}, &Report{Entries: []EntryResult{stale}}); made != 0 || text != "" {
		t.Fatalf("an old stale fact was reported again: %q", text)
	}
	if _, _, fixed := changeReport(&Report{Entries: []EntryResult{stale}}, &Report{Entries: []EntryResult{fresh}}); fixed != 1 {
		t.Fatalf("a fix was not counted")
	}
}

func TestScanUsesContentHashesAndStates(t *testing.T) {
	dir := repo(t)
	writeFile(t, dir, "docs/s.md", "The api key is 7d074302abcdef12 here.\n")
	writeFile(t, dir, "docs/old.md", "<!-- knos-sync: historical -->\nIn the past 300 users came.\n")
	c := mustLoad(t, dir)
	st, err := openState(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()
	res, err := runScan(dir, c, st, false)
	if err != nil {
		t.Fatal(err)
	}
	if res.Files != 3 || res.Changed != 3 {
		t.Fatalf("first scan: %d files, %d changed", res.Files, res.Changed)
	}
	states := map[string]string{}
	for _, cd := range res.Candidates {
		states[cd.Kind+" "+cd.Value] = cd.State
	}
	if states["count 12,010"] != StateLinked || states["hash (withheld)"] != StateSecret || states["count 300"] != StateHistorical {
		t.Fatalf("states: %v", states)
	}
	if res, err = runScan(dir, c, st, false); err != nil || res.Changed != 0 {
		t.Fatalf("second scan changed %d (%v)", res.Changed, err)
	}
	writeFile(t, dir, "docs/a.md", "# A\n\nWe list 12,010 companies today, and 5 more.\n")
	if res, err = runScan(dir, c, st, false); err != nil || res.Changed != 1 {
		t.Fatalf("after one edit, changed %d (%v)", res.Changed, err)
	}
}

func TestJSONSpanEditsKeepEveryOtherByte(t *testing.T) {
	dir := repo(t)
	raw := []byte(readFile(t, dir, FactsPath))
	out, err := setValue(raw, []string{"entries", "[id=rows]", "confirmed_by_person"}, "true")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Replace(string(raw), `"confirmed_by_person": false`, `"confirmed_by_person": true`, 1) != string(out) {
		t.Fatalf("setValue changed more than one value:\n%s", out)
	}
	out, err = appendItem(out, []string{"silenced"}, Silence{ID: "rows", File: "docs/a.md", Says: "1", Actual: "2", Reason: "not useful", Date: "2026-11-16"})
	if err != nil {
		t.Fatal(err)
	}
	if out, err = bumpCount(out, []string{"kinds", "count", "not_useful"}); err != nil {
		t.Fatal(err)
	}
	var c Facts
	if err := json.Unmarshal(out, &c); err != nil || len(c.Silenced) != 1 || c.Kinds["count"].NotUseful != 1 {
		t.Fatalf("after edits: %v %+v", err, c)
	}
}

// The committed sync/facts.json is valid, and none of its places is one an existing check already holds (E1).
func TestTheRepositoryFactsFile(t *testing.T) {
	root, err := filepath.Abs("..")
	if err != nil {
		t.Fatal(err)
	}
	if !exists(filepath.Join(root, "sync", "facts.json")) {
		t.Skip("no sync/facts.json above this folder")
	}
	c, raw, err := loadFacts(root)
	if err != nil {
		t.Fatal(err)
	}
	if raw == nil || len(c.Entries) == 0 {
		t.Fatal("sync/facts.json has no entries")
	}
	cov := loadCoverage(root, c)
	for _, e := range c.Entries {
		for _, p := range e.Places {
			content, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(p.File)))
			if err != nil {
				t.Errorf("%s: %v", e.ID, err)
				continue
			}
			if _, gen := lineFlags(content, c); gen[p.Line] != "" {
				t.Errorf("%s: %s:%d is written by a script (%s)", e.ID, p.File, p.Line, gen[p.Line])
			}
			if by := cov.holds(p.File, p.Says); by != "" {
				t.Errorf("%s: %s:%d %s is already checked by %s", e.ID, p.File, p.Line, p.Says, by)
			}
		}
	}
	for k, s := range c.Kinds {
		if s.Block && !blockable[k] {
			t.Errorf("kind %s blocks", k)
		}
	}
}
