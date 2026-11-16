package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

// Place and entry statuses.
const (
	StatusFresh    = "fresh"    // the text holds against the true value
	StatusStale    = "stale"    // the text no longer holds: a notice with the exact replacement
	StatusBroken   = "broken"   // the fact's text is no longer found: the link is broken, not the fact (SYNC/P4.md where wrong 9)
	StatusError    = "error"    // the command gave no value: its source of truth cannot be found (SYNC/P2.md finding 20)
	StatusRecord   = "record"   // the text was changed to the true value; sync/facts.json still holds the old text
	StatusSilenced = "silenced" // a person marked this notice "not useful"
	StatusOff      = "off"      // the kind's notices are off
)

// PlaceResult is one place of an entry, as check found it.
type PlaceResult struct {
	File   string `json:"file"`
	Line   int    `json:"line"`
	Says   string `json:"says"`
	Stated string `json:"stated,omitempty"`
	Now    string `json:"now,omitempty"`
	Should string `json:"should,omitempty"`
	Status string `json:"status"`
	First  string `json:"first_stale_commit,omitempty"`
	start  int    // byte offsets of the stated value in the file
	end    int
	newVal string // the true value written the way the text wrote the old one
}

// EntryResult is one entry, as check found it.
type EntryResult struct {
	ID        string        `json:"id"`
	Kind      string        `json:"kind"`
	Subject   string        `json:"subject"`
	Command   string        `json:"command"`
	Actual    string        `json:"actual,omitempty"`
	Error     string        `json:"error,omitempty"`
	Status    string        `json:"status"`
	Volatile  bool          `json:"volatile"`
	Reread    bool          `json:"reread"`
	Confirmed bool          `json:"confirmed_by_person"`
	Blocking  bool          `json:"blocking"`
	Places    []PlaceResult `json:"places"`
}

// Report is what `check --json` prints.
type Report struct {
	Commit     string            `json:"commit"`
	Entries    []EntryResult     `json:"entries"`
	Verified   int               `json:"verified"`
	Total      int               `json:"total"`
	KindsOff   []string          `json:"kinds_off"`
	Pointed    int               `json:"pointed"`
	Outside    int               `json:"outside"`
	FileHashes map[string]string `json:"file_hashes"`
	Exit       int               `json:"exit"`
}

type checkOptions struct {
	network    bool
	rereadWait time.Duration
	only       map[string]bool
}

// fileCache reads each file once and keeps its content hash: files are compared by content, never by time (E6).
type fileCache struct {
	root   string
	data   map[string][]byte
	hashes map[string]string
}

func (fc *fileCache) get(rel string) ([]byte, error) {
	if b, ok := fc.data[rel]; ok {
		return b, nil
	}
	b, err := os.ReadFile(filepath.Join(fc.root, filepath.FromSlash(rel)))
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(b)
	fc.data[rel], fc.hashes[rel] = b, hex.EncodeToString(sum[:])
	return b, nil
}

type located struct {
	found  bool
	line   int
	stated string
	now    string
	prefix string
	suffix string
	start  int // byte offsets of the stated value in the file
	end    int
}

func valuePattern(kind, says string) string {
	switch kind {
	case KindCount, KindPrice:
		m := numberCore.FindStringIndex(says)
		if m == nil {
			return regexp.QuoteMeta(says)
		}
		return regexp.QuoteMeta(says[:m[0]]) + `[0-9][0-9,]*(?:\.[0-9]+)?` + regexp.QuoteMeta(says[m[1]:])
	case KindVersion:
		if strings.HasPrefix(says, "v") {
			return `v[0-9]+(?:\.[0-9]+)+(?:-[0-9A-Za-z.]+)?`
		}
		return `[0-9]+(?:\.[0-9]+)+(?:-[0-9A-Za-z.]+)?`
	case KindHash:
		return `[0-9a-fA-F]{8,}`
	}
	return "[^\\s\"'<>()\\[\\]`]+"
}

// locate finds a place's text: on its line first, else on the nearest line where the text around the value
// still stands. The value itself may differ; that is what check compares.
func locate(content []byte, kind string, p Place) located {
	i := strings.Index(p.Text, p.Says)
	if i < 0 {
		return located{}
	}
	prefix, suffix := p.Text[:i], p.Text[i+len(p.Says):]
	re, err := regexp.Compile(regexp.QuoteMeta(prefix) + "(" + valuePattern(kind, p.Says) + ")" + regexp.QuoteMeta(suffix))
	if err != nil {
		return located{}
	}
	starts := []int{0}
	for j, c := range content {
		if c == '\n' {
			starts = append(starts, j+1)
		}
	}
	lineAt := func(n int) (string, int) { // 1-based
		a := starts[n-1]
		b := len(content)
		if n < len(starts) {
			b = starts[n] - 1
		}
		s := string(content[a:b])
		return strings.TrimSuffix(s, "\r"), a
	}
	try := func(n int) (located, bool) {
		if n < 1 || n > len(starts) {
			return located{}, false
		}
		s, off := lineAt(n)
		m := re.FindStringSubmatchIndex(s)
		if m == nil {
			return located{}, false
		}
		return located{found: true, line: n, stated: s[m[2]:m[3]], now: s[m[0]:m[1]], prefix: prefix, suffix: suffix,
			start: off + m[2], end: off + m[3]}, true
	}
	if l, ok := try(p.Line); ok {
		return l
	}
	for d := 1; d <= len(starts); d++ {
		if l, ok := try(p.Line - d); ok {
			return l
		}
		if l, ok := try(p.Line + d); ok {
			return l
		}
	}
	return located{}
}

func commandString(argv []string) string {
	parts := make([]string, len(argv))
	for i, a := range argv {
		if a == "" || strings.ContainsAny(a, " \t\"'") {
			parts[i] = fmt.Sprintf("%q", a)
		} else {
			parts[i] = a
		}
	}
	return "knos-sync value " + strings.Join(parts, " ")
}

// evaluate checks one entry once.
func evaluate(fc *fileCache, c *Facts, e Entry, opt checkOptions) EntryResult {
	r := EntryResult{ID: e.ID, Kind: e.Kind, Subject: e.Subject, Command: commandString(e.Command), Volatile: e.volatile(),
		Confirmed: e.ConfirmedByPerson, Status: StatusFresh}
	if !c.kindOn(e.Kind) {
		r.Status = StatusOff
		return r
	}
	actual, err := trueValue(fc.root, e, opt.network)
	if err != nil {
		r.Status, r.Error = StatusError, err.Error()
		return r
	}
	r.Actual = actual
	stale, broken, record := false, false, false
	for _, p := range e.Places {
		pr := PlaceResult{File: p.File, Line: p.Line, Says: p.Says, Status: StatusFresh}
		content, err := fc.get(p.File)
		if err != nil {
			pr.Status = StatusBroken
			broken = true
			r.Places = append(r.Places, pr)
			continue
		}
		loc := locate(content, e.Kind, p)
		if !loc.found {
			pr.Status = StatusBroken
			broken = true
			r.Places = append(r.Places, pr)
			continue
		}
		pr.Line, pr.Stated, pr.Now, pr.start, pr.end = loc.line, loc.stated, loc.now, loc.start, loc.end
		ok, err := compare(e.Kind, e.Comparator, loc.stated, actual, e.Tolerance)
		switch {
		case err != nil || !ok:
			replacement := formatLike(e.Kind, loc.stated, actual)
			pr.Should = loc.prefix + replacement + loc.suffix
			pr.newVal = replacement
			pr.Status = StatusStale
			if c.silenced(e.ID, p.File, loc.stated, actual) {
				pr.Status = StatusSilenced
			} else {
				stale = true
			}
		case loc.stated != p.Says || loc.line != p.Line:
			pr.Status = StatusRecord
			record = true
		}
		r.Places = append(r.Places, pr)
	}
	switch {
	case stale:
		r.Status = StatusStale
	case broken:
		r.Status = StatusBroken
	case record:
		r.Status = StatusRecord
	}
	return r
}

// runCheck checks every entry (or the ones in opt.only).
func runCheck(root string, c *Facts, st *State, opt checkOptions) *Report {
	fc := &fileCache{root: root, data: map[string][]byte{}, hashes: map[string]string{}}
	rep := &Report{Commit: currentCommit(root), FileHashes: fc.hashes}
	for _, k := range Kinds {
		if !c.kindOn(k) {
			rep.KindsOff = append(rep.KindsOff, k)
		}
	}
	for _, p := range c.Pointers {
		if p.CheckedBy == CheckedOutside {
			rep.Outside++
		} else {
			rep.Pointed++
		}
	}
	for _, e := range c.Entries {
		if len(opt.only) > 0 && !opt.only[e.ID] {
			continue
		}
		r := evaluate(fc, c, e, opt)
		// A value read from a chain or a clock is read once more after a wait before it is reported (E7).
		if e.volatile() && (r.Status == StatusStale || r.Status == StatusError) {
			if opt.rereadWait > 0 {
				time.Sleep(opt.rereadWait)
			}
			r = evaluate(fc, c, e, opt)
			r.Reread = true
		}
		if r.Actual != "" {
			src := e.Source
			if src == "" {
				src = "repo"
			}
			st.recordValue(e.ID, r.Actual, src)
		}
		for i := range r.Places {
			p := &r.Places[i]
			if p.Status == StatusStale {
				p.First = st.firstFailure(e.ID, p.File, p.Stated, r.Actual, rep.Commit)
			}
		}
		set := c.Kinds[e.Kind]
		r.Blocking = (r.Status == StatusStale || r.Status == StatusError) && blockable[e.Kind] && set != nil && set.Block &&
			e.ConfirmedByPerson && !e.volatile()
		if r.Blocking {
			rep.Exit = 1
		}
		if r.Status == StatusFresh || r.Status == StatusRecord {
			rep.Verified++
		}
		if r.Status != StatusOff {
			rep.Total++
		}
		rep.Entries = append(rep.Entries, r)
	}
	return rep
}

func currentCommit(root string) string {
	if s := os.Getenv("GITHUB_SHA"); s != "" {
		return s
	}
	out, err := exec.Command("git", "-C", root, "rev-parse", "HEAD").Output()
	if err != nil {
		return "unknown"
	}
	return strings.TrimSpace(string(out))
}

func short(sha string) string {
	if len(sha) > 12 {
		return sha[:12]
	}
	return sha
}

// noticeText prints one entry's notice: every place with its file, line, the text now and the exact text it
// should be (E6), one notice for every place of one fact (E5).
func noticeText(r EntryResult) string {
	var b strings.Builder
	switch r.Status {
	case StatusStale:
		fmt.Fprintf(&b, "STALE %s (%s): %s\n  true value %s, from: %s\n", r.ID, r.Kind, r.Subject, r.Actual, r.Command)
		for _, p := range r.Places {
			switch p.Status {
			case StatusStale:
				fmt.Fprintf(&b, "  %s:%d\n    now:       %s\n    should be: %s\n", p.File, p.Line, p.Now, p.Should)
				if p.First != "" {
					fmt.Fprintf(&b, "    first seen stale at commit %s\n", short(p.First))
				}
			case StatusSilenced:
				fmt.Fprintf(&b, "  %s:%d  marked not useful\n", p.File, p.Line)
			case StatusBroken:
				fmt.Fprintf(&b, "  %s:%d  the fact's text is no longer there: %q\n", p.File, p.Line, p.Says)
			}
		}
		fmt.Fprintf(&b, "  fix every place: knos-sync fix %s    not useful: knos-sync silence %s\n", r.ID, r.ID)
	case StatusBroken:
		fmt.Fprintf(&b, "LINK BROKEN %s (%s): %s\n", r.ID, r.Kind, r.Subject)
		for _, p := range r.Places {
			if p.Status == StatusBroken {
				fmt.Fprintf(&b, "  %s:%d  the fact's text is no longer found (it said %q); link it again\n", p.File, p.Line, p.Says)
			}
		}
	case StatusError:
		fmt.Fprintf(&b, "NO VALUE %s (%s): %s\n  %s\n  gave: %s\n", r.ID, r.Kind, r.Subject, r.Command, r.Error)
	case StatusRecord:
		fmt.Fprintf(&b, "RECORD %s: the text now says the true value %s; record it: knos-sync accept %s\n", r.ID, r.Actual, r.ID)
	}
	if r.Status == StatusStale || r.Status == StatusError {
		switch {
		case r.Blocking:
			b.WriteString("  this blocks: its kind blocks and a person confirmed it\n")
		case r.Volatile:
			b.WriteString("  read twice, 60 seconds apart; a value from a chain or a clock never blocks\n")
		}
	}
	return b.String()
}

func printText(rep *Report, unconfirmed []Entry) {
	n := 0
	for _, r := range rep.Entries {
		if s := noticeText(r); s != "" {
			fmt.Print(s)
			fmt.Println()
			n++
		}
	}
	if len(rep.KindsOff) > 0 {
		fmt.Printf("kinds with notices off: %s\n", strings.Join(rep.KindsOff, ", "))
	}
	fmt.Printf("verified: %d of %d entries; %d notices; exit %d\n", rep.Verified, rep.Total, n, rep.Exit)
	if unconfirmed != nil {
		fmt.Printf("\n%d entries no person has confirmed:\n", len(unconfirmed))
		for _, e := range unconfirmed {
			fmt.Printf("  knos-sync confirm %s    # %s\n", e.ID, e.Subject)
		}
	}
}

func mdCode(s string) string {
	s = strings.ReplaceAll(s, "`", "'")
	return "`" + s + "`"
}

// noticeMarkdown is one entry's notice for a pull request comment or a run summary.
func noticeMarkdown(r EntryResult) string {
	var b strings.Builder
	switch r.Status {
	case StatusStale:
		fmt.Fprintf(&b, "**%s** (%s): %s. True value %s, from %s\n\n", r.ID, r.Kind, r.Subject, mdCode(r.Actual), mdCode(r.Command))
		for _, p := range r.Places {
			if p.Status == StatusStale {
				fmt.Fprintf(&b, "- %s line %d: %s should be %s\n", mdCode(p.File), p.Line, mdCode(p.Now), mdCode(p.Should))
			}
		}
		fmt.Fprintf(&b, "\nFix every place: %s. Not useful: %s.\n\n", mdCode("knos-sync fix "+r.ID), mdCode("knos-sync silence "+r.ID))
	case StatusBroken:
		fmt.Fprintf(&b, "**%s** (%s): the fact's text is no longer found. Link it again.\n\n", r.ID, r.Kind)
	case StatusError:
		fmt.Fprintf(&b, "**%s** (%s): %s gave no value: %s\n\n", r.ID, r.Kind, mdCode(r.Command), mdCode(r.Error))
	}
	return b.String()
}

func printMarkdown(rep *Report) {
	fmt.Println("### knos-sync check")
	fmt.Println()
	for _, r := range rep.Entries {
		fmt.Print(noticeMarkdown(r))
	}
	fmt.Printf("Verified: %d of %d entries. Exit %d.\n", rep.Verified, rep.Total, rep.Exit)
	if len(rep.KindsOff) > 0 {
		fmt.Printf("Kinds with notices off: %s.\n", strings.Join(rep.KindsOff, ", "))
	}
}

func cmdCheck(args []string) (int, error) {
	set := flag.NewFlagSet("check", flag.ContinueOnError)
	rootF := set.String("root", "", "repository root")
	asJSON := set.Bool("json", false, "print JSON")
	md := set.Bool("markdown", false, "print Markdown")
	unconf := set.Bool("unconfirmed", false, "also list every entry no person has confirmed")
	network := set.Bool("network", false, "let entries whose source is network read it")
	wait := set.Duration("reread-wait", 60*time.Second, "wait before reading a chain or clock value again")
	if err := set.Parse(args); err != nil {
		return 2, err
	}
	root, err := resolveRoot(*rootF)
	if err != nil {
		return 2, err
	}
	c, _, err := loadFacts(root)
	if err != nil {
		return 2, err
	}
	st, err := openState(root)
	if err != nil {
		fmt.Fprintf(os.Stderr, "knos-sync: the state file could not be opened (%v); checking without it\n", err)
		st = nil
	}
	defer st.Close()
	opt := checkOptions{network: *network, rereadWait: *wait, only: map[string]bool{}}
	for _, id := range set.Args() {
		if e, _ := c.entry(id); e == nil {
			return 2, fmt.Errorf("no entry %q in %s", id, FactsPath)
		}
		opt.only[id] = true
	}
	rep := runCheck(root, c, st, opt)
	var unconfirmed []Entry
	if *unconf {
		unconfirmed = []Entry{}
		for _, e := range c.Entries {
			if !e.ConfirmedByPerson {
				unconfirmed = append(unconfirmed, e)
			}
		}
	}
	switch {
	case *asJSON:
		out, err := encodeJSON(rep, "")
		if err != nil {
			return 2, err
		}
		fmt.Println(string(out))
	case *md:
		printMarkdown(rep)
		if unconfirmed != nil {
			fmt.Printf("\n%d entries no person has confirmed.\n", len(unconfirmed))
		}
	default:
		printText(rep, unconfirmed)
	}
	return rep.Exit, nil
}

func placeKey(id string, p PlaceResult, actual string) string {
	return id + "\x00" + p.File + "\x00" + p.Stated + "\x00" + actual
}

// changeReport compares a check of the base with a check of the head: only what the change made stale is
// reported (SYNC/P6.md strongest rule 7), and what it fixed is counted (SYNC/P6.md finding 24).
func changeReport(base, head *Report) (string, int, int) {
	before := map[string]bool{}
	staleBefore := map[string]bool{}
	for _, r := range base.Entries {
		if r.Status == StatusStale || r.Status == StatusBroken || r.Status == StatusError {
			staleBefore[r.ID] = true
		}
		for _, p := range r.Places {
			if p.Status == StatusStale || p.Status == StatusBroken {
				before[placeKey(r.ID, p, r.Actual)] = true
			}
		}
		if r.Status == StatusError {
			before[r.ID+"\x00error"] = true
		}
	}
	var b strings.Builder
	made, fixed := 0, 0
	for _, r := range head.Entries {
		nr := r
		nr.Places = nil
		for _, p := range r.Places {
			if (p.Status == StatusStale || p.Status == StatusBroken) && !before[placeKey(r.ID, p, r.Actual)] {
				nr.Places = append(nr.Places, p)
			}
		}
		newErr := r.Status == StatusError && !before[r.ID+"\x00error"]
		if len(nr.Places) > 0 || newErr {
			if len(nr.Places) > 0 && nr.Status != StatusStale {
				nr.Status = StatusBroken
				for _, p := range nr.Places {
					if p.Status == StatusStale {
						nr.Status = StatusStale
					}
				}
			}
			b.WriteString(noticeMarkdown(nr))
			made++
		}
		if staleBefore[r.ID] && (r.Status == StatusFresh || r.Status == StatusRecord) {
			fixed++
		}
	}
	if made == 0 && fixed == 0 {
		return "", 0, 0
	}
	var out strings.Builder
	out.WriteString("<!-- knos-sync -->\n")
	if made > 0 {
		fmt.Fprintf(&out, "### %d stated facts this change made stale\n\n", made)
		out.WriteString(b.String())
	}
	if fixed > 0 {
		fmt.Fprintf(&out, "Fixed by this change: %d.\n", fixed)
	}
	return out.String(), made, fixed
}

func readReport(path string) (*Report, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	rep := &Report{}
	if len(strings.TrimSpace(string(raw))) == 0 {
		return rep, nil
	}
	if err := json.Unmarshal(raw, rep); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return rep, nil
}

func cmdReport(args []string) (int, error) {
	set := flag.NewFlagSet("report", flag.ContinueOnError)
	basePath := set.String("base", "", "check --json of the base")
	headPath := set.String("head", "", "check --json of the head")
	if err := set.Parse(args); err != nil {
		return 2, err
	}
	if *basePath == "" || *headPath == "" {
		return 2, fmt.Errorf("give --base and --head")
	}
	base, err := readReport(*basePath)
	if err != nil {
		return 2, err
	}
	head, err := readReport(*headPath)
	if err != nil {
		return 2, err
	}
	text, _, _ := changeReport(base, head)
	fmt.Print(text)
	return 0, nil
}

// sortedKeys is used by tests and reports that want a stable order.
func sortedKeys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
