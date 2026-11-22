package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"runtime/debug"
	"sort"
	"strings"
)

// Scan states. A candidate is enforced only when it is linked (SYNC/P2.md where wrong 1: the rest is "unlinked",
// not "failed").
const (
	StateLinked     = "linked"
	StateCovered    = "covered"     // an existing check already holds it (E1)
	StateGenerated  = "generated"   // inside a block a script writes
	StateUnlinked   = "unlinked"    // a candidate nobody has linked
	StateHistorical = "historical"  // a dated or archived file (SYNC/P4.md finding 8)
	StateIgnored    = "ignored"     // a "knos-sync: ignore" marker on the line or the line above
	StateSecret     = "secret-like" // never stored (SYNC/P1.md finding 19)
	StateUnverif    = "unverifiable" // a registered value whose source is outside the repository
	StateNotMC      = "not machine-checkable"
)

var stateOrder = []string{StateLinked, StateCovered, StateGenerated, StateUnverif, StateUnlinked, StateHistorical, StateIgnored, StateSecret}

// ScanResult is what `scan --json` prints.
type ScanResult struct {
	Files         int                       `json:"files"`
	Changed       int                       `json:"changed"`
	Counts        map[string]map[string]int `json:"counts"`
	Candidates    []Candidate               `json:"candidates"`
	PeakMemoryMiB uint64                    `json:"peak_memory_mib"`
	MemoryCapMiB  uint64                    `json:"memory_cap_mib"`
}

// defaultMemCapMiB is a quarter of an 8 GB PC's memory, the budget rule SYNC/P5.md reads in CBM; the 8 GB Windows PC
// is the hardest target and is tested first (SYNC/P1.md).
const defaultMemCapMiB = 2048

// memoryLine says the run's peak memory against its cap; over is true when the peak passed the cap.
func memoryLine(peak, capMiB uint64) (string, bool) {
	if peak == 0 {
		return fmt.Sprintf("peak memory: not readable on this system; cap %d MiB", capMiB), false
	}
	return fmt.Sprintf("peak memory: %d MiB of a %d MiB cap", peak>>20, capMiB), peak > capMiB<<20
}

// scopeFiles lists README.md, every .md under docs/ and every .html under web/, sorted, as slash paths.
func scopeFiles(root string, c *Facts) ([]string, error) {
	var out []string
	if p := filepath.Join(root, "README.md"); exists(p) && optedIn(p, c) {
		out = append(out, "README.md")
	}
	for _, top := range []string{"docs", "web"} {
		base := filepath.Join(root, top)
		if !exists(base) {
			continue
		}
		err := filepath.WalkDir(base, func(p string, d fs.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if d.IsDir() {
				if d.Name() == "node_modules" || d.Name() == ".git" {
					return filepath.SkipDir
				}
				return nil
			}
			rel, err := filepath.Rel(root, p)
			if err != nil {
				return err
			}
			rel = filepath.ToSlash(rel)
			if inScope(rel, c.Skip) && optedIn(p, c) {
				out = append(out, rel)
			}
			return nil
		})
		if err != nil {
			return nil, err
		}
	}
	sort.Strings(out)
	return out, nil
}

// OptInMarker opts one file in when sync/facts.json sets opt_in: teams opt in file by file (SYNC/P6.md finding 14).
const OptInMarker = "knos-sync: on"

// optedIn: every file in scope is read, unless opt_in is set; then only a file that holds the marker.
func optedIn(p string, c *Facts) bool {
	if !c.OptIn {
		return true
	}
	content, err := os.ReadFile(p)
	return err == nil && bytes.Contains(content, []byte(OptInMarker))
}

// docLines reads a doc's lines as a reader sees them: Markdown for .md, visible text for HTML.
func docLines(rel string, content []byte) []lineText {
	if strings.HasSuffix(strings.ToLower(rel), ".md") {
		return markdownLines(content)
	}
	return htmlLines(content)
}

// candidatesOf extracts a file's candidates, before their state is known.
func candidatesOf(rel string, content []byte) []Candidate {
	var out []Candidate
	for _, lt := range docLines(rel, content) {
		for _, c := range extractLine(lt) {
			c.File = rel
			out = append(out, c)
		}
	}
	return out
}

// coverage knows which values the existing checks hold, per file (E1).
type coverage struct {
	byFile map[string]map[string]string // file -> normalised value -> the check that holds it
}

type factsFile struct {
	Facts []struct {
		Say []string `json:"say"`
		Doc string   `json:"doc"`
	} `json:"facts"`
}

func normValue(v string) string {
	return strings.TrimSpace(strings.ReplaceAll(v, ",", ""))
}

func loadCoverage(root string, c *Facts) *coverage {
	cov := &coverage{byFile: map[string]map[string]string{}}
	put := func(file, value, by string) {
		m := cov.byFile[file]
		if m == nil {
			m = map[string]string{}
			cov.byFile[file] = m
		}
		m[normValue(value)] = by
	}
	for _, ex := range c.Existing {
		if ex.FactsFrom == "" {
			continue
		}
		raw, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(ex.FactsFrom)))
		if err != nil {
			continue
		}
		var ff factsFile
		if json.Unmarshal(raw, &ff) != nil {
			continue
		}
		for _, f := range ff.Facts {
			for _, s := range f.Say {
				for _, file := range ex.Files {
					put(file, s, ex.Name)
				}
				if f.Doc != "" {
					put(f.Doc, s, ex.Name)
				}
			}
		}
	}
	return cov
}

func (cov *coverage) holds(file, value string) string {
	return cov.byFile[file][normValue(value)]
}

// lineFlags reads the raw lines once: ignore markers, generated blocks.
func lineFlags(content []byte, c *Facts) (ignored map[int]bool, generated map[int]string) {
	ignored, generated = map[int]bool{}, map[int]string{}
	var open *Generated
	for i, line := range strings.Split(string(content), "\n") {
		n := i + 1
		if strings.Contains(line, "knos-sync: ignore") {
			ignored[n], ignored[n+1] = true, true
		}
		if open == nil {
			for gi := range c.Generated {
				g := &c.Generated[gi]
				if strings.Contains(line, g.Start) && !strings.Contains(line, g.End) {
					open = g
					break
				}
			}
		}
		if open != nil {
			generated[n] = open.By
			if strings.Contains(line, open.End) {
				open = nil
			}
		}
		if strings.Contains(line, "[[stat:") {
			generated[n] = "python scripts/bench_docs.py --check"
		}
	}
	return ignored, generated
}

// classify sets each candidate's state.
func classify(rel string, content []byte, cands []Candidate, c *Facts, cov *coverage) {
	hist := c.historical(rel, content)
	ignored, generated := lineFlags(content, c)
	lines := strings.Split(string(content), "\n")
	for i := range cands {
		cd := &cands[i]
		raw := ""
		if cd.Line >= 1 && cd.Line <= len(lines) {
			raw = lines[cd.Line-1]
		}
		switch {
		case (cd.Kind == KindHash || cd.Kind == KindSentence) && reSecret.MatchString(raw):
			cd.State, cd.Value, cd.Text = StateSecret, "(withheld)", "(withheld)"
		case hist:
			cd.State = StateHistorical
		case ignored[cd.Line]:
			cd.State = StateIgnored
		case generated[cd.Line] != "":
			cd.State, cd.By = StateGenerated, generated[cd.Line]
		case cd.Kind == KindSentence:
			cd.State = StateNotMC
		default:
			if id := linkedBy(c, rel, cd.Line, cd.Value); id != "" {
				cd.State, cd.By = StateLinked, id
			} else if p := c.pointerAt(rel, cd.Value); p != nil && p.CheckedBy == CheckedOutside {
				cd.State, cd.By = StateUnverif, p.ID
			} else if p != nil {
				cd.State, cd.By = StateCovered, p.CheckedBy
			} else if by := cov.holds(rel, cd.Value); by != "" {
				cd.State, cd.By = StateCovered, by
			} else {
				cd.State = StateUnlinked
			}
		}
	}
}

func linkedBy(c *Facts, file string, line int, value string) string {
	for _, e := range c.Entries {
		for _, p := range e.Places {
			if p.File == file && p.Line == line && normValue(p.Says) == normValue(value) {
				return e.ID
			}
		}
	}
	return ""
}

// runScan reads every file in scope; a file whose content hash is unchanged reuses its stored candidates
// (SYNC/P5.md finding 19). full re-reads everything, which is also a normal, fast path (SYNC/P5.md finding 20).
func runScan(root string, c *Facts, st *State, full bool) (*ScanResult, error) {
	files, err := scopeFiles(root, c)
	if err != nil {
		return nil, err
	}
	cov := loadCoverage(root, c)
	res := &ScanResult{Counts: map[string]map[string]int{}}
	keep := map[string]bool{}
	for _, rel := range files {
		content, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(rel)))
		if err != nil {
			return nil, err
		}
		keep[rel] = true
		res.Files++
		sum := sha256.Sum256(content)
		sha := hex.EncodeToString(sum[:])
		var cands []Candidate
		old, known := st.fileHash(rel)
		if !full && known && old == sha {
			if cands, err = st.cachedCandidates(rel); err != nil {
				cands = nil
				known = false
			}
		}
		if full || !known || old != sha {
			res.Changed++
			cands = candidatesOf(rel, content)
			// secrets are withheld before anything is stored
			classify(rel, content, cands, c, cov)
			for i := range cands {
				if cands[i].State == StateSecret {
					cands[i].Value, cands[i].Text = "(withheld)", "(withheld)"
				}
			}
			if err := st.storeFile(rel, sha, content, cands); err != nil {
				return nil, err
			}
		}
		classify(rel, content, cands, c, cov)
		for _, cd := range cands {
			m := res.Counts[cd.Kind]
			if m == nil {
				m = map[string]int{}
				res.Counts[cd.Kind] = m
			}
			m[cd.State]++
		}
		res.Candidates = append(res.Candidates, cands...)
	}
	if err := st.forget(keep); err != nil {
		return nil, err
	}
	return res, nil
}

func cmdScan(args []string) (int, error) {
	set := flag.NewFlagSet("scan", flag.ContinueOnError)
	rootF := set.String("root", "", "repository root")
	list := set.Bool("list", false, "print every candidate")
	asJSON := set.Bool("json", false, "print JSON")
	full := set.Bool("full", false, "read every file again, ignoring stored hashes")
	capMiB := set.Uint64("mem-cap-mib", defaultMemCapMiB, "the memory cap in MiB: a soft limit for the collector, and exit 1 when the peak passes it")
	if err := set.Parse(args); err != nil {
		return 2, err
	}
	if *capMiB == 0 {
		return 2, fmt.Errorf("the memory cap must be above 0 MiB")
	}
	defer debug.SetMemoryLimit(debug.SetMemoryLimit(int64(*capMiB << 20)))
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
		fmt.Fprintf(os.Stderr, "knos-sync: the state file could not be opened (%v); reading every file\n", err)
		st = nil
	}
	defer st.Close()
	res, err := runScan(root, c, st, *full || st == nil)
	if err != nil {
		return 2, err
	}
	peak := peakMemory()
	memLine, over := memoryLine(peak, *capMiB)
	res.PeakMemoryMiB, res.MemoryCapMiB = peak>>20, *capMiB
	code := 0
	if over {
		code = 1
	}
	if *asJSON {
		out, err := encodeJSON(res, "")
		if err != nil {
			return 2, err
		}
		fmt.Println(string(out))
		return code, nil
	}
	fmt.Printf("knos-sync scan: %d files read, %d changed since the last scan\n%s\n\n", res.Files, res.Changed, memLine)
	fmt.Printf("%-10s", "kind")
	for _, s := range stateOrder {
		fmt.Printf(" %12s", s)
	}
	fmt.Println()
	for _, k := range Kinds {
		fmt.Printf("%-10s", k)
		for _, s := range stateOrder {
			fmt.Printf(" %12d", res.Counts[k][s])
		}
		on := "on"
		if !c.kindOn(k) {
			on = "off"
		}
		fmt.Printf("   notices %s\n", on)
	}
	fmt.Printf("\n%d other factual sentences: %s\n", res.Counts[KindSentence][StateNotMC], StateNotMC)
	if *list {
		fmt.Println()
		for _, cd := range res.Candidates {
			by := ""
			if cd.By != "" {
				by = "  (" + cd.By + ")"
			}
			fmt.Printf("%s:%d  %s  %s  %s%s\n", cd.File, cd.Line, cd.Kind, cd.State, cd.Value, by)
		}
	}
	return code, nil
}
