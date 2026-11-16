package main

import (
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

// writeFacts writes sync/facts.json only if the edited bytes still parse and validate.
func writeFacts(root string, raw []byte) error {
	if _, err := parseFacts(raw); err != nil {
		return fmt.Errorf("the change was not written: %w", err)
	}
	return os.WriteFile(filepath.Join(root, filepath.FromSlash(FactsPath)), raw, 0o644)
}

func needFacts(root string) (*Facts, []byte, error) {
	c, raw, err := loadFacts(root)
	if err != nil {
		return nil, nil, err
	}
	if raw == nil {
		return nil, nil, errors.New(FactsPath + " does not exist")
	}
	return c, raw, nil
}

// idFirst takes a leading positional id off args, so that `confirm <id> --root X` and `confirm --root X <id>` both work.
func idFirst(args []string) (string, []string) {
	if len(args) > 0 && !strings.HasPrefix(args[0], "-") {
		return args[0], args[1:]
	}
	return "", args
}

// cmdConfirm: a person says an entry's link is right (E8).
func cmdConfirm(args []string) (int, error) {
	id, args := idFirst(args)
	set := flag.NewFlagSet("confirm", flag.ContinueOnError)
	rootF := set.String("root", "", "repository root")
	if err := set.Parse(args); err != nil {
		return 2, err
	}
	if id == "" && set.NArg() > 0 {
		id = set.Arg(0)
	}
	if id == "" {
		return 2, errors.New("give the entry's id: knos-sync confirm <id>")
	}
	root, err := resolveRoot(*rootF)
	if err != nil {
		return 2, err
	}
	c, raw, err := needFacts(root)
	if err != nil {
		return 2, err
	}
	if e, _ := c.entry(id); e == nil {
		return 2, fmt.Errorf("no entry %q in %s", id, FactsPath)
	}
	out, err := setValue(raw, []string{"entries", "[id=" + id + "]", "confirmed_by_person"}, "true")
	if err != nil {
		return 2, err
	}
	if err := writeFacts(root, out); err != nil {
		return 2, err
	}
	fmt.Printf("%s: confirmed_by_person is true\n", id)
	return 0, nil
}

// evaluateOne checks one entry now, without the state file.
func evaluateOne(root string, c *Facts, e Entry, network bool) EntryResult {
	fc := &fileCache{root: root, data: map[string][]byte{}, hashes: map[string]string{}}
	return evaluate(fc, c, e, checkOptions{network: network})
}

// cmdSilence marks an entry's current notice "not useful" (SYNC/P2.md finding 23; SYNC/P6.md finding 2). The mark
// holds while the text and the true value stay the same, and it is counted for the entry's kind.
func cmdSilence(args []string) (int, error) {
	id, args := idFirst(args)
	set := flag.NewFlagSet("silence", flag.ContinueOnError)
	rootF := set.String("root", "", "repository root")
	file := set.String("file", "", "only the place in this file")
	reason := set.String("reason", "not useful", "why")
	if err := set.Parse(args); err != nil {
		return 2, err
	}
	if id == "" && set.NArg() > 0 {
		id = set.Arg(0)
	}
	if id == "" {
		return 2, errors.New("give the entry's id: knos-sync silence <id>")
	}
	root, err := resolveRoot(*rootF)
	if err != nil {
		return 2, err
	}
	c, raw, err := needFacts(root)
	if err != nil {
		return 2, err
	}
	e, _ := c.entry(id)
	if e == nil {
		return 2, fmt.Errorf("no entry %q in %s", id, FactsPath)
	}
	r := evaluateOne(root, c, *e, false)
	n := 0
	for _, p := range r.Places {
		if p.Status != StatusStale || (*file != "" && p.File != *file) {
			continue
		}
		s := Silence{ID: id, File: p.File, Says: p.Stated, Actual: r.Actual, Reason: *reason, Date: time.Now().UTC().Format("2006-01-02")}
		if raw, err = appendItem(raw, []string{"silenced"}, s); err != nil {
			return 2, err
		}
		n++
	}
	if n == 0 {
		return 2, fmt.Errorf("%s has no stale place to silence", id)
	}
	if raw, err = bumpCount(raw, []string{"kinds", e.Kind, "not_useful"}); err != nil {
		return 2, err
	}
	if err := writeFacts(root, raw); err != nil {
		return 2, err
	}
	fmt.Printf("%s: %d notice(s) marked %q; counted for the kind %s\n", id, n, *reason, e.Kind)
	return 0, nil
}

// recordPlaces writes what each changed place says now into sync/facts.json, sets the expected value and counts
// the act for the kind.
func recordPlaces(raw []byte, e Entry, r EntryResult, changed map[int]PlaceResult) ([]byte, error) {
	var err error
	idx := make([]int, 0, len(changed))
	for i := range changed {
		idx = append(idx, i)
	}
	sort.Ints(idx)
	for _, i := range idx {
		p := changed[i]
		base := []string{"entries", "[id=" + e.ID + "]", "places", "[" + strconv.Itoa(i) + "]"}
		if raw, err = setValue(raw, append(base, "line"), strconv.Itoa(p.Line)); err != nil {
			return nil, err
		}
		if raw, err = setValue(raw, append(base, "text"), jsonLiteral(p.Now)); err != nil {
			return nil, err
		}
		if raw, err = setValue(raw, append(base, "says"), jsonLiteral(p.Stated)); err != nil {
			return nil, err
		}
	}
	if raw, err = setValue(raw, []string{"entries", "[id=" + e.ID + "]", "expected"}, jsonLiteral(r.Actual)); err != nil {
		return nil, err
	}
	return bumpCount(raw, []string{"kinds", e.Kind, "acted_on"})
}

// cmdFix writes the true value into every stale place of the named entries (all stale entries when none is
// named): one fact, every place, one command (SYNC/P6.md where wrong 8). Bytes change only at the value's span.
func cmdFix(args []string) (int, error) {
	set := flag.NewFlagSet("fix", flag.ContinueOnError)
	rootF := set.String("root", "", "repository root")
	if err := set.Parse(args); err != nil {
		return 2, err
	}
	root, err := resolveRoot(*rootF)
	if err != nil {
		return 2, err
	}
	c, raw, err := needFacts(root)
	if err != nil {
		return 2, err
	}
	want := map[string]bool{}
	for _, id := range set.Args() {
		if e, _ := c.entry(id); e == nil {
			return 2, fmt.Errorf("no entry %q in %s", id, FactsPath)
		}
		want[id] = true
	}
	type edit struct {
		start, end int
		value      string
	}
	edits := map[string][]edit{}
	fixed := 0
	for _, e := range c.Entries {
		if len(want) > 0 && !want[e.ID] {
			continue
		}
		r := evaluateOne(root, c, e, false)
		if r.Status != StatusStale {
			continue
		}
		changed := map[int]PlaceResult{}
		for i, p := range r.Places {
			if p.Status != StatusStale {
				continue
			}
			edits[p.File] = append(edits[p.File], edit{p.start, p.end, p.newVal})
			np := p
			np.Now, np.Stated = p.Should, p.newVal
			changed[i] = np
			fmt.Printf("%s:%d  %s  ->  %s\n", p.File, p.Line, p.Now, p.Should)
		}
		if raw, err = recordPlaces(raw, e, r, changed); err != nil {
			return 2, err
		}
		fixed++
	}
	if fixed == 0 {
		fmt.Println("nothing is stale")
		return 0, nil
	}
	files := make([]string, 0, len(edits))
	for f := range edits {
		files = append(files, f)
	}
	sort.Strings(files)
	for _, f := range files {
		path := filepath.Join(root, filepath.FromSlash(f))
		content, err := os.ReadFile(path)
		if err != nil {
			return 2, err
		}
		es := edits[f]
		sort.Slice(es, func(i, j int) bool { return es[i].start > es[j].start })
		for k, ed := range es {
			if k > 0 && ed.end > es[k-1].start {
				return 2, fmt.Errorf("%s: two edits overlap; fix one entry at a time", f)
			}
			content = append(content[:ed.start:ed.start], append([]byte(ed.value), content[ed.end:]...)...)
		}
		if err := os.WriteFile(path, content, 0o644); err != nil {
			return 2, err
		}
	}
	if err := writeFacts(root, raw); err != nil {
		return 2, err
	}
	fmt.Printf("fixed %d entries\n", fixed)
	return 0, nil
}

// cmdAccept records text that a person already changed to the true value (SYNC/P4.md finding 34: "accept new
// value", a visible diff in the pull request).
func cmdAccept(args []string) (int, error) {
	id, args := idFirst(args)
	set := flag.NewFlagSet("accept", flag.ContinueOnError)
	rootF := set.String("root", "", "repository root")
	if err := set.Parse(args); err != nil {
		return 2, err
	}
	if id == "" && set.NArg() > 0 {
		id = set.Arg(0)
	}
	root, err := resolveRoot(*rootF)
	if err != nil {
		return 2, err
	}
	c, raw, err := needFacts(root)
	if err != nil {
		return 2, err
	}
	e, _ := c.entry(id)
	if e == nil {
		return 2, fmt.Errorf("no entry %q in %s", id, FactsPath)
	}
	r := evaluateOne(root, c, *e, false)
	changed := map[int]PlaceResult{}
	for i, p := range r.Places {
		if p.Status == StatusRecord {
			changed[i] = p
		}
	}
	if len(changed) == 0 {
		return 2, fmt.Errorf("%s has no place whose text was changed to the true value (status %s)", id, r.Status)
	}
	if raw, err = recordPlaces(raw, *e, r, changed); err != nil {
		return 2, err
	}
	if err := writeFacts(root, raw); err != nil {
		return 2, err
	}
	fmt.Printf("%s: %d place(s) recorded; expected is %s\n", id, len(changed), r.Actual)
	return 0, nil
}

type stringList []string

func (s *stringList) String() string     { return strings.Join(*s, ",") }
func (s *stringList) Set(v string) error { *s = append(*s, v); return nil }

func parsePlace(v string) (string, int, error) {
	i := strings.LastIndex(v, ":")
	if i <= 0 {
		return "", 0, fmt.Errorf("a place is FILE:LINE, not %q", v)
	}
	n, err := strconv.Atoi(v[i+1:])
	if err != nil || n < 1 {
		return "", 0, fmt.Errorf("a place is FILE:LINE, not %q", v)
	}
	return filepath.ToSlash(v[:i]), n, nil
}

// placeText picks the fact's text on a line: the value and a few words after it (or before it, at a line's end),
// enough to find it again when the line moves.
func placeText(line, says string) (string, error) {
	i := strings.Index(line, says)
	if i < 0 {
		return "", fmt.Errorf("the line does not say %q", says)
	}
	if strings.Count(line, says) > 1 {
		return "", fmt.Errorf("the line says %q more than once; give --text", says)
	}
	end := i + len(says)
	stop := end + 30
	if stop >= len(line) {
		stop = len(line)
	} else {
		for stop > end && line[stop] != ' ' {
			stop--
		}
	}
	text := strings.TrimRight(line[i:stop], " ")
	if len(text) <= len(says)+3 {
		start := i - 30
		if start < 0 {
			start = 0
		}
		for start < i && start > 0 && line[start-1] != ' ' {
			start++
		}
		text = strings.TrimLeft(line[start:end], " ")
	}
	return text, nil
}

// isCommon: a value that a wrong command reproduces by chance (SYNC/P4.md where wrong 10).
func isCommon(kind, value string) bool {
	if !numericKind(kind) {
		return false
	}
	f, ok := parseNumber(value)
	if !ok {
		return false
	}
	switch f {
	case 0, 1, 2, 3, 4, 5, 10, 12, 20, 24, 50, 60, 100, 1000:
		return true
	}
	return f < 10 && f == float64(int(f))
}

// newPlace reads a place and refuses one an existing check already holds (E1: no second mechanism).
func newPlace(root string, c *Facts, file string, line int, says, text string) (Place, error) {
	if !inScope(file, c.Skip) {
		return Place{}, fmt.Errorf("%s is not a file knos-sync reads", file)
	}
	content, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(file)))
	if err != nil {
		return Place{}, err
	}
	lines := strings.Split(string(content), "\n")
	if line > len(lines) {
		return Place{}, fmt.Errorf("%s has %d lines", file, len(lines))
	}
	l := strings.TrimSuffix(lines[line-1], "\r")
	if text == "" {
		if text, err = placeText(l, says); err != nil {
			return Place{}, fmt.Errorf("%s:%d: %w", file, line, err)
		}
	}
	if !strings.Contains(l, text) || !strings.Contains(text, says) {
		return Place{}, fmt.Errorf("%s:%d does not hold %q, or the text does not hold %q", file, line, text, says)
	}
	_, generated := lineFlags(content, c)
	if by := generated[line]; by != "" {
		return Place{}, fmt.Errorf("%s:%d is written by a script and checked by `%s`; it is not linked twice", file, line, by)
	}
	if by := loadCoverage(root, c).holds(file, says); by != "" {
		return Place{}, fmt.Errorf("%s:%d: %s is already checked by %s; it is not linked twice", file, line, says, by)
	}
	return Place{File: file, Line: line, Text: text, Says: says}, nil
}

// cmdLink adds an entry, or a place to one, only when the command reproduces the value the text states (E4). No
// model decides; a link starts unconfirmed until a person runs knos-sync confirm.
func cmdLink(args []string) (int, error) {
	set := flag.NewFlagSet("link", flag.ContinueOnError)
	rootF := set.String("root", "", "repository root")
	id := set.String("id", "", "entry id")
	kind := set.String("kind", "", "version, hash, count, price or name")
	subject := set.String("subject", "", "what the value is about")
	says := set.String("says", "", "the value as the text writes it")
	text := set.String("text", "", "the fact's text on the line (default: the value and a few words)")
	comparator := set.String("comparator", "equal", "equal, at_least, at_most, approximately, rounded, prefix")
	tolerance := set.Float64("tolerance", 0, "for approximately: a share of the true value")
	convert := set.String("convert", "", "mul:N;div:N;add:N;round:N")
	source := set.String("source", "", "repo, chain, clock or network")
	var places stringList
	set.Var(&places, "place", "FILE:LINE (repeat for each place)")
	if err := set.Parse(args); err != nil {
		return 2, err
	}
	if *id == "" || len(places) == 0 || *says == "" {
		return 2, errors.New("give --id, --says and at least one --place")
	}
	root, err := resolveRoot(*rootF)
	if err != nil {
		return 2, err
	}
	c, raw, err := needFacts(root)
	if err != nil {
		return 2, err
	}
	existing, _ := c.entry(*id)
	var e Entry
	if existing != nil {
		e = *existing
	} else {
		e = Entry{ID: *id, Kind: *kind, Subject: *subject, Command: set.Args(), Comparator: *comparator,
			Tolerance: *tolerance, Convert: *convert, Source: *source}
		if p := commandProblem(e); p != "" {
			return 2, errors.New(p)
		}
	}
	actual, err := trueValue(root, e, false)
	if err != nil {
		return 2, fmt.Errorf("the command gave no value: %w", err)
	}
	ok, err := compare(e.Kind, e.Comparator, *says, actual, e.Tolerance)
	if err != nil {
		return 2, err
	}
	if !ok {
		return 1, fmt.Errorf("not linked: the command gives %q and the text says %q", actual, *says)
	}
	var added []Place
	for _, pv := range places {
		f, n, err := parsePlace(pv)
		if err != nil {
			return 2, err
		}
		p, err := newPlace(root, c, f, n, *says, *text)
		if err != nil {
			return 2, err
		}
		added = append(added, p)
	}
	if existing != nil {
		for _, p := range added {
			if raw, err = appendItem(raw, []string{"entries", "[id=" + e.ID + "]", "places"}, p); err != nil {
				return 2, err
			}
		}
	} else {
		e.Places, e.Expected = added, actual
		if raw, err = appendItem(raw, []string{"entries"}, e); err != nil {
			return 2, err
		}
	}
	if err := writeFacts(root, raw); err != nil {
		return 2, err
	}
	fmt.Printf("%s: linked %d place(s); the command gives %s\n", e.ID, len(added), actual)
	if isCommon(e.Kind, actual) {
		fmt.Printf("%s is a common value that a wrong command can give by chance: a person must look before confirming\n", actual)
	}
	fmt.Printf("a person confirms it with: knos-sync confirm %s\n", e.ID)
	return 0, nil
}

// cmdPropose lists unlinked text that states an entry's value: a new copy of a known fact (SYNC/P6.md finding 21;
// SYNC/P3.md where wrong 10, value matching). It proposes; only link, which runs the command, adds anything.
func cmdPropose(args []string) (int, error) {
	set := flag.NewFlagSet("propose", flag.ContinueOnError)
	rootF := set.String("root", "", "repository root")
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
	res, err := runScan(root, c, nil, true)
	if err != nil {
		return 2, err
	}
	n := 0
	for _, cd := range res.Candidates {
		if cd.State != StateUnlinked || isCommon(cd.Kind, cd.Value) {
			continue
		}
		for _, e := range c.Entries {
			if e.Kind != cd.Kind {
				continue
			}
			same := normValue(cd.Value) == normValue(e.Expected)
			if numericKind(e.Kind) {
				a, ok1 := parseNumber(cd.Value)
				b, ok2 := parseNumber(e.Expected)
				same = ok1 && ok2 && a == b
			}
			if same {
				fmt.Printf("%s:%d says %s, the value of %s: knos-sync link --id %s --place %s:%d --says %q\n",
					cd.File, cd.Line, cd.Value, e.ID, e.ID, cd.File, cd.Line, cd.Value)
				n++
			}
		}
	}
	fmt.Printf("%d possible copies\n", n)
	return 0, nil
}
