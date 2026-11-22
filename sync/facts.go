package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// FactsPath is the one committed file of links (E4).
const FactsPath = "sync/facts.json"

// The five kinds of E3, in their order. "sentence" is the sixth listing: a factual sentence no kind can check.
const (
	KindVersion  = "version"
	KindHash     = "hash"
	KindCount    = "count"
	KindPrice    = "price"
	KindName     = "name"
	KindSentence = "sentence"
)

// Kinds lists the five checkable kinds in E3's order.
var Kinds = []string{KindVersion, KindHash, KindCount, KindPrice, KindName}

// blockable: only kinds with a deterministic re-check may fail a push (SYNC/P6.md finding 3 and strongest rule 3:
// "hash, version, count"); a name and a price are notices only.
var blockable = map[string]bool{KindVersion: true, KindHash: true, KindCount: true}

// Comparators (SYNC/P4.md finding 28).
var numericComparators = map[string]bool{"equal": true, "at_least": true, "at_most": true, "approximately": true, "rounded": true}
var stringComparators = map[string]bool{"equal": true, "prefix": true}

// Sources: where the true value comes from. Values from a chain, a clock or the network are volatile: re-read once
// after a wait before they are reported, and never a reason for exit code 1 (E7; SYNC/P2.md finding 9).
var sources = map[string]bool{"": true, "repo": true, "chain": true, "clock": true, "network": true}

// Place is one spot where a fact's text appears.
type Place struct {
	File string `json:"file"`
	Line int    `json:"line"`
	Text string `json:"text"`
	Says string `json:"says"`
}

// Entry links one fact, stated in one or more places, to the command that produces its true value.
type Entry struct {
	ID                string   `json:"id"`
	Kind              string   `json:"kind"`
	Subject           string   `json:"subject"`
	Places            []Place  `json:"places"`
	Command           []string `json:"command"`
	Expected          string   `json:"expected"`
	Comparator        string   `json:"comparator"`
	Tolerance         float64  `json:"tolerance,omitempty"`
	Convert           string   `json:"convert,omitempty"`
	Source            string   `json:"source,omitempty"`
	ConfirmedByPerson bool     `json:"confirmed_by_person"`
}

// KindSetting turns a kind's notices on or off and lets it block. Blocking is opt-in per kind (SYNC/P6.md where
// wrong 2). not_useful and acted_on count marks per kind: when "not useful" passes 10% of the marks, the kind's
// notices turn off (SYNC/P6.md strongest rule 2).
type KindSetting struct {
	On        bool `json:"on"`
	Block     bool `json:"block"`
	NotUseful int  `json:"not_useful"`
	ActedOn   int  `json:"acted_on"`
}

// Existing names a check the repository already runs. knos-sync points at it and never checks its facts again (E1).
type Existing struct {
	Name      string   `json:"name"`
	Command   string   `json:"command"`
	RunBy     string   `json:"run_by"`
	Checks    string   `json:"checks"`
	Files     []string `json:"files,omitempty"`
	FactsFrom string   `json:"facts_from,omitempty"`
}

// Generated marks a block a script writes: its lines are that script's to keep true.
type Generated struct {
	Start string `json:"start"`
	End   string `json:"end"`
	By    string `json:"by"`
}

// Silence is one notice a person marked "not useful". It holds while the text and the true value stay the same.
type Silence struct {
	ID     string `json:"id"`
	File   string `json:"file"`
	Says   string `json:"says"`
	Actual string `json:"actual"`
	Reason string `json:"reason"`
	Date   string `json:"date"`
}

// Pointer registers a fact that knos-sync does not check itself: an existing check holds it (E1: no second
// mechanism), or its source is outside the repository and nothing here can re-check it ("outside"; SYNC/P2.md
// finding 22: "unverifiable" is its own state). scan marks the value in those files with that state.
type Pointer struct {
	ID        string   `json:"id"`
	Kind      string   `json:"kind"`
	Subject   string   `json:"subject"`
	Value     string   `json:"value"`
	Where     []string `json:"where"`
	Source    string   `json:"source"`
	CheckedBy string   `json:"checked_by"`
}

// CheckedOutside marks a pointer whose source is outside the repository.
const CheckedOutside = "outside"

// Facts is sync/facts.json.
type Facts struct {
	Note       string                  `json:"_"`
	Skip       []string                `json:"skip"`
	Historical []string                `json:"historical"`
	OptIn      bool                    `json:"opt_in,omitempty"` // read only the files that hold OptInMarker
	Kinds      map[string]*KindSetting `json:"kinds"`
	Existing   []Existing              `json:"existing"`
	Generated  []Generated             `json:"generated"`
	Entries    []Entry                 `json:"entries"`
	Pointers   []Pointer               `json:"pointers"`
	Silenced   []Silence               `json:"silenced"`
}

var idPattern = regexp.MustCompile(`^[a-z0-9][a-z0-9-]*$`)

// defaultFacts is what a repository without sync/facts.json gets: few kinds on, none blocking (SYNC/P6.md
// strongest rule 4: "Turn few claim kinds on by default").
func defaultFacts() *Facts {
	c := &Facts{Kinds: map[string]*KindSetting{}}
	for _, k := range Kinds {
		c.Kinds[k] = &KindSetting{On: k != KindName}
	}
	return c
}

// loadFacts reads root/sync/facts.json. A missing file is an empty set of links; a file that does not parse or
// does not validate is an error.
func loadFacts(root string) (*Facts, []byte, error) {
	raw, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(FactsPath)))
	if errors.Is(err, os.ErrNotExist) {
		return defaultFacts(), nil, nil
	}
	if err != nil {
		return nil, nil, err
	}
	c, err := parseFacts(raw)
	if err != nil {
		return nil, raw, err
	}
	return c, raw, nil
}

func parseFacts(raw []byte) (*Facts, error) {
	c := &Facts{}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(c); err != nil {
		return nil, fmt.Errorf("%s does not parse: %w", FactsPath, err)
	}
	if c.Kinds == nil {
		c.Kinds = map[string]*KindSetting{}
	}
	for _, k := range Kinds {
		if c.Kinds[k] == nil {
			c.Kinds[k] = &KindSetting{On: k != KindName}
		}
	}
	if problems := c.Validate(); len(problems) > 0 {
		return nil, fmt.Errorf("%s is not valid:\n  %s", FactsPath, strings.Join(problems, "\n  "))
	}
	return c, nil
}

// Validate returns every problem with the file, one line each.
func (c *Facts) Validate() []string {
	var out []string
	known := map[string]bool{}
	for _, k := range Kinds {
		known[k] = true
	}
	names := make([]string, 0, len(c.Kinds))
	for k := range c.Kinds {
		names = append(names, k)
	}
	sort.Strings(names)
	for _, k := range names {
		s := c.Kinds[k]
		if !known[k] {
			out = append(out, fmt.Sprintf("kinds: %q is not one of version, hash, count, price, name", k))
			continue
		}
		if s.Block && !blockable[k] {
			out = append(out, fmt.Sprintf("kinds.%s: only version, hash and count may block a push", k))
		}
		if s.NotUseful < 0 || s.ActedOn < 0 {
			out = append(out, fmt.Sprintf("kinds.%s: counts cannot be negative", k))
		}
	}
	seen := map[string]bool{}
	for i, e := range c.Entries {
		where := fmt.Sprintf("entries[%d] (%s)", i, e.ID)
		if !idPattern.MatchString(e.ID) {
			out = append(out, where+": the id must be lower-case letters, digits and hyphens")
		}
		if seen[e.ID] {
			out = append(out, where+": the id is used twice")
		}
		seen[e.ID] = true
		if !known[e.Kind] {
			out = append(out, where+": the kind must be one of version, hash, count, price, name")
		}
		if numericKind(e.Kind) && !numericComparators[e.Comparator] {
			out = append(out, where+": a count or a price compares with equal, at_least, at_most, approximately or rounded")
		}
		if !numericKind(e.Kind) && known[e.Kind] && !stringComparators[e.Comparator] {
			out = append(out, where+": a version, hash or name compares with equal or prefix")
		}
		if e.Tolerance < 0 || e.Tolerance >= 1 {
			out = append(out, where+": the tolerance is a share between 0 and 1")
		}
		if !sources[e.Source] {
			out = append(out, where+": the source must be repo, chain, clock or network")
		}
		if strings.TrimSpace(e.Subject) == "" {
			out = append(out, where+": the subject says what the number is about")
		}
		if e.Expected == "" {
			out = append(out, where+": the expected value is empty")
		}
		if _, err := parseConvert(e.Convert); err != nil {
			out = append(out, where+": "+err.Error())
		}
		if p := commandProblem(e); p != "" {
			out = append(out, where+": "+p)
		}
		if len(e.Places) == 0 {
			out = append(out, where+": an entry lists every place its fact appears, and has none")
		}
		for j, p := range e.Places {
			pw := fmt.Sprintf("%s places[%d]", where, j)
			if p.File == "" || strings.Contains(p.File, `\`) || strings.HasPrefix(p.File, "/") || strings.Contains(p.File, "..") {
				out = append(out, pw+": the file is a path relative to the repository, with forward slashes")
			} else if !inScope(p.File, c.Skip) {
				out = append(out, pw+": "+p.File+" is not a file knos-sync reads (README.md, docs/**/*.md, web/**/*.html)")
			}
			if p.Line < 1 {
				out = append(out, pw+": the line starts at 1")
			}
			if p.Says == "" || !strings.Contains(p.Text, p.Says) {
				out = append(out, pw+": the text must contain what it says")
			}
			if strings.ContainsAny(p.Text, "\r\n") {
				out = append(out, pw+": the text is on one line")
			}
		}
	}
	existing := map[string]bool{CheckedOutside: true}
	for _, ex := range c.Existing {
		existing[ex.Name] = true
	}
	for i, p := range c.Pointers {
		where := fmt.Sprintf("pointers[%d] (%s)", i, p.ID)
		if !idPattern.MatchString(p.ID) {
			out = append(out, where+": the id must be lower-case letters, digits and hyphens")
		}
		if seen[p.ID] {
			out = append(out, where+": the id is used twice")
		}
		seen[p.ID] = true
		if !known[p.Kind] {
			out = append(out, where+": the kind must be one of version, hash, count, price, name")
		}
		if p.Value == "" || p.Subject == "" || p.Source == "" {
			out = append(out, where+": a pointer gives its value, its subject and its source")
		}
		if !existing[p.CheckedBy] {
			out = append(out, where+": checked_by must name a check in existing, or be outside")
		}
		for _, f := range p.Where {
			if !inScope(f, c.Skip) {
				out = append(out, where+": "+f+" is not a file knos-sync reads")
			}
		}
	}
	return out
}

func (c *Facts) pointerAt(file, value string) *Pointer {
	for i := range c.Pointers {
		p := &c.Pointers[i]
		if normValue(p.Value) != normValue(value) {
			continue
		}
		for _, f := range p.Where {
			if f == file {
				return p
			}
		}
	}
	return nil
}

func numericKind(kind string) bool { return kind == KindCount || kind == KindPrice }

// commandProblem says what is wrong with an entry's command, or "".
func commandProblem(e Entry) string {
	if len(e.Command) == 0 {
		return "the command is empty"
	}
	b, ok := builtins[e.Command[0]]
	if !ok {
		return fmt.Sprintf("the command starts with %q; it must start with one of %s", e.Command[0], strings.Join(builtinNames(), ", "))
	}
	if len(e.Command)-1 < b.minArgs {
		return fmt.Sprintf("%s needs %d arguments", e.Command[0], b.minArgs)
	}
	// never let a doc prove a doc (SYNC/P2.md strongest rule 8): a value is read from data or code, not prose
	if b.readsFile {
		f := strings.ToLower(e.Command[1])
		if strings.HasSuffix(f, ".md") || strings.HasSuffix(f, ".html") || strings.HasSuffix(f, ".htm") {
			return "the value is read from a document (" + e.Command[1] + "); a document cannot prove a document"
		}
	}
	if e.Source == "chain" {
		final := false
		for _, a := range e.Command {
			if strings.Contains(a, "finalized") {
				final = true
			}
		}
		if !final {
			return "a value from a chain is read at finalized: the command must say so (SYNC/P4.md finding 31)"
		}
	}
	if e.Command[0] == "http-status" && e.Source != "network" {
		return "http-status reads the network, and only an entry whose source is network may use it"
	}
	return ""
}

// volatile: the value can change between two runs without any commit.
func (e Entry) volatile() bool { return e.Source == "chain" || e.Source == "clock" || e.Source == "network" }

func (c *Facts) entry(id string) (*Entry, int) {
	for i := range c.Entries {
		if c.Entries[i].ID == id {
			return &c.Entries[i], i
		}
	}
	return nil, -1
}

// kindOn: the kind's notices are on, and "not useful" marks have not passed 10% of all marks for it.
func (c *Facts) kindOn(kind string) bool {
	s := c.Kinds[kind]
	if s == nil || !s.On {
		return false
	}
	return !overNotUseful(s)
}

func overNotUseful(s *KindSetting) bool {
	marks := s.NotUseful + s.ActedOn
	return s.NotUseful > 0 && s.NotUseful*10 > marks
}

func (c *Facts) silenced(id, file, says, actual string) bool {
	for _, s := range c.Silenced {
		if s.ID == id && s.File == file && s.Says == says && s.Actual == actual {
			return true
		}
	}
	return false
}

// inScope: README.md, every .md under docs/ and every .html under web/ (E3), minus the skipped folders.
func inScope(rel string, skip []string) bool {
	for _, s := range skip {
		if strings.HasPrefix(rel, s) {
			return false
		}
	}
	for _, seg := range strings.Split(rel, "/") {
		if seg == "node_modules" || seg == "repos" {
			return false
		}
	}
	lower := strings.ToLower(rel)
	switch {
	case rel == "README.md":
		return true
	case strings.HasPrefix(rel, "docs/") && strings.HasSuffix(lower, ".md"):
		return true
	case strings.HasPrefix(rel, "web/") && (strings.HasSuffix(lower, ".html") || strings.HasSuffix(lower, ".htm")):
		return true
	}
	return false
}

func (c *Facts) historical(rel string, content []byte) bool {
	for _, h := range c.Historical {
		if matched, _ := path.Match(h, rel); matched || (strings.HasSuffix(h, "/") && strings.HasPrefix(rel, h)) {
			return true
		}
	}
	return bytes.Contains(content, []byte("knos-sync: historical"))
}

// encodeJSON writes v as the repository writes JSON: one space per level, no HTML escaping.
func encodeJSON(v any, prefix string) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	enc.SetIndent(prefix, " ")
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimRight(buf.Bytes(), "\n"), nil
}
