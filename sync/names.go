package main

import (
	"bufio"
	"io/fs"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
)

// Names (L54). A code name in a doc is a link that must resolve, checked on every run (SYNC/P2.md finding 1). A
// committed line is reported only when its name resolved at the commit that last wrote the line (SYNC/P4.md: the
// git-history gate); git history then tells a rename, with the new name, from a removal (SYNC/P2.md finding 8). A
// line not committed yet is being written now: a path on it that does not resolve is reported as it stands. Without
// git history nothing can say when a line was written, so nothing is reported.
const (
	NameRenamed = "renamed"
	NameRemoved = "removed"
	NameNew     = "not found"
)

// NameFinding is one code name in a doc that does not resolve.
type NameFinding struct {
	File    string `json:"file"`
	Line    int    `json:"line"`
	Name    string `json:"name"`
	Ident   bool   `json:"identifier"`
	Status  string `json:"status"`
	NewName string `json:"new_name,omitempty"`
	Written string `json:"written_at,omitempty"`
}

// CodeName is one definition in a code file, kept as a span (file and line), never as a copy of its text.
type CodeName struct {
	Name     string
	Keyword  string
	File     string
	Line     int
	Top      bool // the definition starts at the line's first column
	Exported bool // written with export (JavaScript) or pub (Rust)
}

var codeExts = map[string]bool{".py": true, ".go": true, ".js": true, ".mjs": true, ".ts": true, ".rs": true}

var codePathspecs = []string{"*.py", "*.go", "*.js", "*.mjs", "*.ts", "*.rs"}

// skipDirs are never read for code: tools, caches, other repositories and knos-sync's own state.
var skipDirs = map[string]bool{".git": true, "node_modules": true, ".venv": true, "venv": true, "__pycache__": true,
	"target": true, ".knos-sync": true, "repos": true}

// reDef finds a definition: def, class, func (with or without a receiver), function, fn, type, const, let or var.
// Groups: 1 export, 2 pub, 3 the keyword, 4 the name.
var reDef = regexp.MustCompile(`^\s*(export\s+)?(pub\s+)?(?:async\s+)?(def|class|func|function|fn|type|const|let|var)\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)`)

// reCall is a code span that names a function: name() or a.b.name().
var reCall = regexp.MustCompile(`^(?:[A-Za-z_][A-Za-z0-9_]*\.)*([A-Za-z_][A-Za-z0-9_]*)\(\)$`)

// walkCode calls fn for every line of every code file under root, with the file as a slash path.
func walkCode(root string, exts map[string]bool, fn func(rel string, n int, line string)) error {
	return filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil // an unreadable folder or file is left out
		}
		if d.IsDir() {
			if p != root && skipDirs[d.Name()] {
				return filepath.SkipDir
			}
			return nil
		}
		if !exts[strings.ToLower(filepath.Ext(p))] {
			return nil
		}
		info, err := d.Info()
		if err != nil || info.Size() > 1<<20 {
			return nil
		}
		rel, err := filepath.Rel(root, p)
		if err != nil {
			return err
		}
		f, err := os.Open(p)
		if err != nil {
			return nil
		}
		defer f.Close()
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 64*1024), 1<<20)
		n := 0
		for sc.Scan() {
			n++
			fn(filepath.ToSlash(rel), n, sc.Text())
		}
		return nil
	})
}

// codeNames lists every definition in the repository's code files.
func codeNames(root string) ([]CodeName, error) {
	var out []CodeName
	err := walkCode(root, codeExts, func(rel string, n int, line string) {
		if m := reDef.FindStringSubmatch(line); m != nil {
			top := line != "" && line[0] != ' ' && line[0] != '\t'
			out = append(out, CodeName{Name: m[4], Keyword: m[3], File: rel, Line: n, Top: top, Exported: m[1] != "" || m[2] != ""})
		}
	})
	return out, err
}

// nameRef is one code name a doc line uses, with the repository paths it may mean.
type nameRef struct {
	name  string
	ident bool
	paths []string
}

// lineRefs lists the code names on one doc line: paths with a folder (in prose or a code span), link targets that are
// files, and function names written as name() in a code span.
func lineRefs(doc string, lt lineText) []nameRef {
	var out []nameRef
	seen := map[string]bool{}
	addPath := func(p string) {
		if seen[p] {
			return
		}
		if ps := pathCandidates(doc, p); len(ps) > 0 {
			seen[p] = true
			out = append(out, nameRef{name: p, paths: ps})
		}
	}
	for _, m := range rePath.FindAllString(reURL.ReplaceAllString(lt.Text, " "), -1) {
		if strings.Contains(m, "/") {
			addPath(m)
		}
	}
	for _, c := range lt.Code {
		if m := reCall.FindStringSubmatch(c); m != nil {
			if !seen[m[1]+"()"] {
				seen[m[1]+"()"] = true
				out = append(out, nameRef{name: m[1], ident: true})
			}
			continue
		}
		if rePath.FindString(c) == c && strings.Contains(c, "/") {
			addPath(c)
		}
	}
	for _, l := range lt.Links {
		if strings.Contains(l, ":") || strings.HasPrefix(l, "#") {
			continue // a scheme (https:, mailto:) or an anchor
		}
		if i := strings.IndexAny(l, "#?"); i >= 0 {
			l = l[:i]
		}
		if l != "" && rePath.FindString(l) == l {
			addPath(l)
		}
	}
	return out
}

// pathCandidates lists the repository paths a doc's path may mean: from the root, and from the doc's own folder. A
// first part with a dot in it (a domain such as example.com) is not a path in the repository.
func pathCandidates(doc, p string) []string {
	first := strings.SplitN(strings.TrimPrefix(p, "/"), "/", 2)[0]
	if strings.Contains(p, "/") && strings.Contains(strings.TrimPrefix(first, "."), ".") {
		return nil
	}
	var out []string
	add := func(c string) {
		c = path.Clean(c)
		if c == "." || c == ".." || strings.HasPrefix(c, "../") {
			return
		}
		for _, o := range out {
			if o == c {
				return
			}
		}
		out = append(out, c)
	}
	if strings.HasPrefix(p, "/") {
		add(strings.TrimLeft(p, "/"))
		return out
	}
	add(p)
	if d := path.Dir(doc); d != "." {
		add(path.Join(d, p))
	}
	return out
}

func anyExists(root string, paths []string) bool {
	for _, p := range paths {
		if exists(filepath.Join(root, filepath.FromSlash(p))) {
			return true
		}
	}
	return false
}

// git runs git in root and returns what it prints.
func git(root string, args ...string) (string, error) {
	out, err := exec.Command("git", append([]string{"-C", root}, args...)...).Output()
	return string(out), err
}

// hasHistory: root is inside a git work tree that has at least one commit.
func hasHistory(root string) bool {
	_, err := git(root, "rev-parse", "--verify", "-q", "HEAD")
	return err == nil
}

// blameLines maps each line of a file to the commit that last wrote it. A line not committed yet, and every line of
// a file git does not track, is missing from the map.
func blameLines(root, file string) map[int]string {
	lines := map[int]string{}
	out, err := git(root, "blame", "--porcelain", "--", file)
	if err != nil {
		return lines
	}
	for _, l := range strings.Split(out, "\n") {
		if strings.HasPrefix(l, "\t") {
			continue // the line's own text
		}
		f := strings.Fields(l)
		if len(f) < 3 || (len(f[0]) != 40 && len(f[0]) != 64) || !reHex.MatchString(f[0]) {
			continue
		}
		n, err := strconv.Atoi(f[2])
		if err != nil || strings.Trim(f[0], "0") == "" {
			continue
		}
		lines[n] = f[0]
	}
	return lines
}

// defPattern is reDef for one name, as an extended regular expression for git grep.
func defPattern(name string) string {
	return `(def|class|func|function|fn|type|const|let|var)[[:space:]]+(\([^)]*\)[[:space:]]*)?` + name + `([^A-Za-z0-9_]|$)`
}

func pathAt(root, sha, p string) bool {
	_, err := git(root, "cat-file", "-e", sha+":./"+p)
	return err == nil
}

// resolvedAt: the name resolved in the tree of commit sha.
func resolvedAt(root, sha string, r nameRef) bool {
	if r.ident {
		args := append([]string{"grep", "-q", "-E", defPattern(r.name), sha, "--"}, codePathspecs...)
		_, err := git(root, args...)
		return err == nil
	}
	for _, p := range r.paths {
		if pathAt(root, sha, p) {
			return true
		}
	}
	return false
}

// renamedPath follows the renames of a path after commit sha and returns its name now, or "" if it was never renamed.
// memo keeps each commit's list of renames, read once.
func renamedPath(root, sha, p string, memo map[string]string) string {
	out, ok := memo[sha]
	if !ok {
		var err error
		if out, err = git(root, "log", "--reverse", "-M", "--relative", "--diff-filter=R", "--name-status", "--format=", sha+"..HEAD"); err != nil {
			out = ""
		}
		memo[sha] = out
	}
	cur, moved := p, false
	for _, l := range strings.Split(out, "\n") {
		f := strings.Split(strings.TrimRight(l, "\r"), "\t")
		if len(f) == 3 && strings.HasPrefix(f[0], "R") && f[1] == cur {
			cur, moved = f[2], true
		}
	}
	if !moved {
		return ""
	}
	return cur
}

type codeDef struct {
	keyword, name string
	block         int // which file's diff of the commit it is in
}

// renameIn reads one commit's removed and added definitions. gone: the name's definition was removed and not added
// back; the new name is a definition with the same keyword added in the same file's diff, whose name was not removed.
func renameIn(name string, removed, added []codeDef) (string, bool) {
	gone := false
	was := map[string]bool{}
	for _, r := range removed {
		was[r.name] = true
		if r.name == name {
			gone = true
		}
	}
	for _, a := range added {
		if a.name == name {
			gone = false // changed or moved in place, still there
		}
	}
	if !gone {
		return "", false
	}
	for _, r := range removed {
		if r.name != name {
			continue
		}
		for _, a := range added {
			if a.block == r.block && a.keyword == r.keyword && !was[a.name] {
				return a.name, true
			}
		}
	}
	return "", true
}

// renamedIdent reads, oldest first, the commits after sha whose diffs touch the name (git log -G), and returns the
// new name from the commit that took its definition away, or "" when it was removed.
func renamedIdent(root, sha, name string) string {
	args := append([]string{"log", "--reverse", "--relative", "-G", name, "--format=commit %H", "-p", "-U0", "--no-color",
		"--no-ext-diff", sha + "..HEAD", "--"}, codePathspecs...)
	out, err := git(root, args...)
	if err != nil {
		return ""
	}
	var removed, added []codeDef
	block, inHunk := 0, false
	for _, l := range strings.Split(out, "\n") {
		l = strings.TrimRight(l, "\r")
		switch {
		case strings.HasPrefix(l, "commit "):
			if n, gone := renameIn(name, removed, added); gone {
				return n
			}
			removed, added, inHunk = nil, nil, false
		case strings.HasPrefix(l, "diff --git "):
			block++
			inHunk = false
		case strings.HasPrefix(l, "@@"):
			inHunk = true
		case inHunk && strings.HasPrefix(l, "+"):
			if m := reDef.FindStringSubmatch(l[1:]); m != nil {
				added = append(added, codeDef{m[3], m[4], block})
			}
		case inHunk && strings.HasPrefix(l, "-"):
			if m := reDef.FindStringSubmatch(l[1:]); m != nil {
				removed = append(removed, codeDef{m[3], m[4], block})
			}
		}
	}
	n, _ := renameIn(name, removed, added)
	return n
}

// newNameOf gives the name a resolved-then reference has now, or "" when it was removed.
func newNameOf(root, sha, doc string, r nameRef, index map[string]int, memo map[string]string) string {
	if r.ident {
		name := r.name
		for hop := 0; hop < 5; hop++ {
			next := renamedIdent(root, sha, name)
			if next == "" || next == name {
				return ""
			}
			if index[next] > 0 {
				return next
			}
			name = next
		}
		return ""
	}
	for i, p := range r.paths {
		if !pathAt(root, sha, p) {
			continue
		}
		now := renamedPath(root, sha, p, memo)
		if now == "" || !exists(filepath.Join(root, filepath.FromSlash(now))) {
			return ""
		}
		if d := path.Dir(doc) + "/"; i > 0 && strings.HasPrefix(now, d) {
			return strings.TrimPrefix(now, d) // the doc named it from its own folder
		}
		return now
	}
	return ""
}

// nameMention is a doc line that names a code name the index holds: an edge of the name graph.
type nameMention struct {
	doc  string
	name string
}

// checkNames finds the code names in docs that do not resolve, by the rule at the top of this file.
func checkNames(root string, c *Facts, st *State) ([]NameFinding, error) {
	if !hasHistory(root) {
		return nil, nil
	}
	files, err := scopeFiles(root, c)
	if err != nil {
		return nil, err
	}
	defs, err := codeNames(root)
	if err != nil {
		return nil, err
	}
	index := map[string]int{}
	for _, d := range defs {
		index[d.Name]++
	}
	var out []NameFinding
	var mentions []nameMention
	memo := map[string]string{}
	for _, rel := range files {
		content, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(rel)))
		if err != nil {
			return nil, err
		}
		if c.historical(rel, content) {
			continue
		}
		ignored, _ := lineFlags(content, c)
		var blame map[int]string
		for _, lt := range docLines(rel, content) {
			if ignored[lt.Line] {
				continue
			}
			for _, r := range lineRefs(rel, lt) {
				if r.ident && index[r.name] > 0 {
					mentions = append(mentions, nameMention{rel, r.name})
					continue
				}
				if !r.ident && anyExists(root, r.paths) {
					continue
				}
				if blame == nil {
					blame = blameLines(root, rel)
				}
				f := NameFinding{File: rel, Line: lt.Line, Name: r.name, Ident: r.ident}
				sha, committed := blame[lt.Line]
				switch {
				case !committed && r.ident:
					continue // a function of a library or of the language: the code index cannot say
				case !committed:
					f.Status = NameNew
				case !resolvedAt(root, sha, r):
					continue // it never resolved: an example or a plan, not a broken link
				default:
					f.Written, f.Status = sha, NameRemoved
					if n := newNameOf(root, sha, rel, r, index, memo); n != "" {
						f.Status, f.NewName = NameRenamed, n
					}
				}
				out = append(out, f)
			}
		}
	}
	if err := st.storeNameGraph(defs, mentions, index); err != nil {
		return nil, err
	}
	return out, nil
}

// nameText is one finding as check prints it.
func nameText(f NameFinding) string {
	name := f.Name
	if f.Ident {
		name += "()"
	}
	switch f.Status {
	case NameRenamed:
		return "NAME " + f.File + ":" + strconv.Itoa(f.Line) + "  " + name + " was renamed to " + f.NewName + "\n"
	case NameRemoved:
		return "NAME " + f.File + ":" + strconv.Itoa(f.Line) + "  " + name + " was removed after commit " + short(f.Written) + "\n"
	}
	return "NAME " + f.File + ":" + strconv.Itoa(f.Line) + "  " + name + " is not found (a line not committed yet)\n"
}
