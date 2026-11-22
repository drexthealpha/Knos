package main

import (
	"flag"
	"fmt"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// CodeConst is a constant a code file sets to a number, with the regex command that reads it back.
type CodeConst struct {
	Name    string
	File    string
	Line    int
	Value   string
	Pattern string
}

// LiteralClaim is a constant in code whose value a doc states: a claim found by fixed rules, not yet linked
// (SYNC/P2.md finding 4: a literal shared by code and a doc becomes a claim). The confidence is 1/n where n constants
// in code have that value: which constant the doc means is its own, uncertain step (SYNC/P4.md).
type LiteralClaim struct {
	Const      CodeConst
	Doc        Candidate
	Confidence float64
	Command    []string
}

var (
	// a module-level constant in Python: NAME = 37 or NAME: int = 37
	reConstPy = regexp.MustCompile(`^([A-Z][A-Z0-9_]*)\s*(?::\s*[A-Za-z_][A-Za-z0-9_.\[\]]*\s*)?=\s*(-?[0-9]+(?:\.[0-9]+)?)\s*(?:#.*)?$`)
	// a const in Go, JavaScript, TypeScript or Rust: const Name = 37, export const NAME = 37;, pub const MAX: u64 = 37;
	reConstKw = regexp.MustCompile(`^\s*(?:export\s+)?(?:pub\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*[^=]+)?=\s*(-?[0-9]+(?:\.[0-9]+)?)\s*;?\s*(?://.*)?$`)
)

// codeConsts lists the constants that code files set to a number.
func codeConsts(root string) ([]CodeConst, error) {
	var out []CodeConst
	err := walkCode(root, codeExts, func(rel string, n int, line string) {
		if strings.HasSuffix(rel, ".py") {
			if m := reConstPy.FindStringSubmatch(line); m != nil {
				out = append(out, CodeConst{Name: m[1], File: rel, Line: n, Value: m[2],
					Pattern: `(?m)^` + m[1] + `\s*(?::[^=\n]*)?=\s*(-?[0-9]+(?:\.[0-9]+)?)`})
			}
			return
		}
		if m := reConstKw.FindStringSubmatch(line); m != nil {
			out = append(out, CodeConst{Name: m[1], File: rel, Line: n, Value: m[2],
				Pattern: `(?m)^\s*(?:export\s+)?(?:pub\s+)?const\s+` + m[1] + `\s*(?::[^=\n]*)?=\s*(-?[0-9]+(?:\.[0-9]+)?)`})
		}
	})
	return out, err
}

// literalClaims pairs each unlinked count or price in the docs with the code constants of the same value. A value a
// wrong pairing gives by chance (0 to 9, 10, 12, 100 and the like) is left out.
func literalClaims(root string, c *Facts) ([]LiteralClaim, error) {
	consts, err := codeConsts(root)
	if err != nil {
		return nil, err
	}
	byValue := map[float64][]CodeConst{}
	for _, k := range consts {
		f, ok := parseNumber(k.Value)
		if !ok || isCommon(KindCount, k.Value) {
			continue
		}
		byValue[f] = append(byValue[f], k)
	}
	if len(byValue) == 0 {
		return nil, nil
	}
	res, err := runScan(root, c, nil, true)
	if err != nil {
		return nil, err
	}
	var out []LiteralClaim
	for _, cd := range res.Candidates {
		if cd.State != StateUnlinked || !numericKind(cd.Kind) {
			continue
		}
		f, ok := parseNumber(cd.Value)
		if !ok {
			continue
		}
		ks := byValue[f]
		for _, k := range ks {
			out = append(out, LiteralClaim{Const: k, Doc: cd, Confidence: 1 / float64(len(ks)),
				Command: []string{"regex", k.File, k.Pattern}})
		}
	}
	return out, nil
}

// linkCommand is the knos-sync link command that turns a literal claim into an entry; link runs the command first.
func (lc LiteralClaim) linkCommand() string {
	id := strings.Trim(strings.ToLower(strings.ReplaceAll(lc.Const.Name, "_", "-")), "-")
	return fmt.Sprintf("knos-sync link --id %s --kind %s --subject %q --place %s:%d --says %q -- regex %s %q",
		id, lc.Doc.Kind, lc.Const.Name+" in "+lc.Const.File, lc.Doc.File, lc.Doc.Line, lc.Doc.Value, lc.Const.File, lc.Const.Pattern)
}

// isTestFile: tests are not code surface a reader calls.
func isTestFile(rel string) bool {
	base := path.Base(rel)
	if strings.HasPrefix(base, "test_") || strings.HasSuffix(base, "_test.go") || strings.Contains(base, ".test.") ||
		strings.Contains(base, ".spec.") {
		return true
	}
	for _, seg := range strings.Split(path.Dir(rel), "/") {
		if seg == "tests" || seg == "test" || seg == "testdata" {
			return true
		}
	}
	return false
}

// isPublic: a top-level def or class without a leading underscore in Python, an exported func or type in Go, a
// definition written with export (JavaScript, TypeScript) or pub (Rust).
func isPublic(d CodeName) bool {
	if isTestFile(d.File) {
		return false
	}
	switch strings.ToLower(path.Ext(d.File)) {
	case ".py":
		return d.Top && (d.Keyword == "def" || d.Keyword == "class") && !strings.HasPrefix(d.Name, "_")
	case ".go":
		return d.Top && (d.Keyword == "func" || d.Keyword == "type") && d.Name[0] >= 'A' && d.Name[0] <= 'Z'
	}
	return d.Exported
}

func isIdentByte(c byte) bool {
	return c == '_' || (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
}

// addWords puts every identifier-like word of b into words.
func addWords(words map[string]bool, b []byte) {
	start := -1
	for i := 0; i <= len(b); i++ {
		ident := i < len(b) && isIdentByte(b[i])
		switch {
		case ident && start < 0:
			start = i
		case !ident && start >= 0:
			words[string(b[start:i])] = true
			start = -1
		}
	}
}

// uncovered lists the public code names no doc in scope mentions (SYNC/P2.md finding 7: also the reverse check, code
// surface never mentioned in docs), and how many public names there are.
func uncovered(root string, c *Facts) ([]CodeName, int, error) {
	files, err := scopeFiles(root, c)
	if err != nil {
		return nil, 0, err
	}
	words := map[string]bool{}
	for _, rel := range files {
		content, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(rel)))
		if err != nil {
			return nil, 0, err
		}
		addWords(words, content)
	}
	defs, err := codeNames(root)
	if err != nil {
		return nil, 0, err
	}
	var out []CodeName
	total := 0
	for _, d := range defs {
		if !isPublic(d) {
			continue
		}
		total++
		if !words[d.Name] {
			out = append(out, d)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].File != out[j].File {
			return out[i].File < out[j].File
		}
		return out[i].Line < out[j].Line
	})
	return out, total, nil
}

func cmdCoverage(args []string) (int, error) {
	set := flag.NewFlagSet("coverage", flag.ContinueOnError)
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
	missing, total, err := uncovered(root, c)
	if err != nil {
		return 2, err
	}
	fmt.Printf("%d of %d public code names: no doc mentions them\n", len(missing), total)
	for _, d := range missing {
		fmt.Printf("  %s:%d  %s\n", d.File, d.Line, d.Name)
	}
	return 0, nil
}
