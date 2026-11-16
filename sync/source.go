package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"math"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// A builtin produces a true value without a shell, the same on Windows, Linux and Mac (SYNC/P2.md finding 30).
type builtin struct {
	minArgs   int
	readsFile bool // its first argument is a file whose content gives the value
	help      string
}

var builtins = map[string]builtin{
	"json":        {2, true, "json FILE PATH: a value in a JSON file; PATH is dotted (a.b.0.c) or a JSON pointer (/a/b)"},
	"regex":       {2, true, "regex FILE PATTERN: the first group of the first match in a file"},
	"count-lines": {2, true, "count-lines FILE PATTERN: how many lines of a file match"},
	"count-files": {2, false, "count-files DIR SUFFIX: how many files under a folder end with SUFFIX"},
	"sha256":      {1, false, "sha256 FILE: the file's SHA-256, in hex"},
	"size":        {1, false, "size FILE: the file's size in bytes"},
	"exists":      {1, false, "exists PATH: the path when it exists, else nothing"},
	"exec":        {1, false, "exec PROGRAM ARGS...: what a program prints, run without a shell"},
	"http-status": {1, false, "http-status URL: the status code a HEAD request gets (network; only with --network)"},
}

func builtinNames() []string {
	out := make([]string, 0, len(builtins))
	for k := range builtins {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

var errNetworkOff = errors.New("this value needs the network; run with --network")

// runCommand gives the raw value of a command, run in root.
func runCommand(root string, argv []string, network bool, timeout time.Duration) (string, error) {
	if len(argv) == 0 {
		return "", errors.New("empty command")
	}
	b, ok := builtins[argv[0]]
	if !ok {
		return "", fmt.Errorf("unknown command %q", argv[0])
	}
	if len(argv)-1 < b.minArgs {
		return "", fmt.Errorf("%s needs %d arguments", argv[0], b.minArgs)
	}
	path := func(p string) string { return filepath.Join(root, filepath.FromSlash(p)) }
	switch argv[0] {
	case "json":
		raw, err := os.ReadFile(path(argv[1]))
		if err != nil {
			return "", err
		}
		return jsonValue(raw, argv[2])
	case "regex":
		raw, err := os.ReadFile(path(argv[1]))
		if err != nil {
			return "", err
		}
		re, err := regexp.Compile(argv[2])
		if err != nil {
			return "", err
		}
		m := re.FindSubmatch(raw)
		if m == nil {
			return "", fmt.Errorf("the pattern is not in %s", argv[1])
		}
		if len(m) > 1 {
			return string(m[1]), nil
		}
		return string(m[0]), nil
	case "count-lines":
		f, err := os.Open(path(argv[1]))
		if err != nil {
			return "", err
		}
		defer f.Close()
		re, err := regexp.Compile(argv[2])
		if err != nil {
			return "", err
		}
		n := 0
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 64*1024), 16*1024*1024)
		for sc.Scan() {
			if re.Match(sc.Bytes()) {
				n++
			}
		}
		if err := sc.Err(); err != nil {
			return "", err
		}
		return strconv.Itoa(n), nil
	case "count-files":
		n := 0
		err := filepath.WalkDir(path(argv[1]), func(p string, d fs.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if !d.IsDir() && strings.HasSuffix(d.Name(), argv[2]) {
				n++
			}
			return nil
		})
		if err != nil {
			return "", err
		}
		return strconv.Itoa(n), nil
	case "sha256":
		raw, err := os.ReadFile(path(argv[1]))
		if err != nil {
			return "", err
		}
		sum := sha256.Sum256(raw)
		return hex.EncodeToString(sum[:]), nil
	case "size":
		info, err := os.Stat(path(argv[1]))
		if err != nil {
			return "", err
		}
		return strconv.FormatInt(info.Size(), 10), nil
	case "exists":
		if exists(path(argv[1])) {
			return argv[1], nil
		}
		return "", nil
	case "exec":
		ctx, cancel := context.WithTimeout(context.Background(), timeout)
		defer cancel()
		cmd := exec.CommandContext(ctx, argv[1], argv[2:]...)
		cmd.Dir = root
		cmd.Env = append(os.Environ(), "KNOS_SYNC_COMMITMENT=finalized")
		var stdout, stderr bytes.Buffer
		cmd.Stdout, cmd.Stderr = &stdout, &stderr
		if err := cmd.Run(); err != nil {
			msg := strings.TrimSpace(stderr.String())
			if len(msg) > 300 {
				msg = msg[:300]
			}
			return "", fmt.Errorf("%s: %v %s", argv[1], err, msg)
		}
		return strings.TrimSpace(stdout.String()), nil
	case "http-status":
		if !network {
			return "", errNetworkOff
		}
		ctx, cancel := context.WithTimeout(context.Background(), timeout)
		defer cancel()
		req, err := http.NewRequestWithContext(ctx, http.MethodHead, argv[1], nil)
		if err != nil {
			return "", err
		}
		req.Header.Set("User-Agent", "knos-sync")
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			return "", err
		}
		resp.Body.Close()
		return strconv.Itoa(resp.StatusCode), nil
	}
	return "", fmt.Errorf("unknown command %q", argv[0])
}

// jsonValue reads one value: a dotted path (keys, or digits for an array index) or a JSON pointer (RFC 6901).
func jsonValue(raw []byte, path string) (string, error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return "", err
	}
	var parts []string
	if strings.HasPrefix(path, "/") {
		for _, p := range strings.Split(path[1:], "/") {
			parts = append(parts, strings.ReplaceAll(strings.ReplaceAll(p, "~1", "/"), "~0", "~"))
		}
	} else if path != "" {
		parts = strings.Split(path, ".")
	}
	for _, p := range parts {
		switch t := v.(type) {
		case map[string]any:
			next, ok := t[p]
			if !ok {
				return "", fmt.Errorf("no key %q", p)
			}
			v = next
		case []any:
			i, err := strconv.Atoi(p)
			if err != nil || i < 0 || i >= len(t) {
				return "", fmt.Errorf("no item %q", p)
			}
			v = t[i]
		default:
			return "", fmt.Errorf("%q is below a value that has no keys", p)
		}
	}
	switch t := v.(type) {
	case json.Number:
		return t.String(), nil
	case string:
		return t, nil
	case bool:
		return strconv.FormatBool(t), nil
	case nil:
		return "", errors.New("the value is null")
	}
	return "", errors.New("the value is a list or an object, not one value")
}

// A conversion turns the command's value into the unit the text uses: "mul:100", "div:100", "round:1", "add:-1",
// joined by ";" and applied in order (SYNC/P2.md where wrong 5: "0.3%" against 30 basis points).
type convertOp struct {
	op  string
	arg float64
}

func parseConvert(s string) ([]convertOp, error) {
	var ops []convertOp
	if strings.TrimSpace(s) == "" {
		return nil, nil
	}
	for _, part := range strings.Split(s, ";") {
		name, arg, ok := strings.Cut(strings.TrimSpace(part), ":")
		if !ok {
			return nil, fmt.Errorf("the conversion %q is not op:number", part)
		}
		f, err := strconv.ParseFloat(arg, 64)
		if err != nil {
			return nil, fmt.Errorf("the conversion %q is not op:number", part)
		}
		switch name {
		case "mul", "div", "add", "round":
		default:
			return nil, fmt.Errorf("the conversion %q is not one of mul, div, add, round", name)
		}
		if name == "div" && f == 0 {
			return nil, errors.New("a conversion divides by zero")
		}
		if name == "round" && (f < 0 || f > 12 || f != math.Trunc(f)) {
			return nil, errors.New("round takes a whole number of decimals from 0 to 12")
		}
		ops = append(ops, convertOp{name, f})
	}
	return ops, nil
}

func applyConvert(value, rule string) (string, error) {
	ops, err := parseConvert(rule)
	if err != nil || len(ops) == 0 {
		return value, err
	}
	f, ok := parseNumber(value)
	if !ok {
		return "", fmt.Errorf("the conversion needs a number and the command gave %q", value)
	}
	for _, o := range ops {
		switch o.op {
		case "mul":
			f *= o.arg
		case "div":
			f /= o.arg
		case "add":
			f += o.arg
		case "round":
			p := math.Pow(10, o.arg)
			f = math.Round(f*p) / p
		}
	}
	// 0.003 x 100 is 0.30000000000000004 in binary; twelve significant digits print it as 0.3
	if g, err := strconv.ParseFloat(strconv.FormatFloat(f, 'g', 12, 64), 64); err == nil {
		f = g
	}
	return strconv.FormatFloat(f, 'f', -1, 64), nil
}

var numberCore = regexp.MustCompile(`[0-9][0-9,]*(?:\.[0-9]+)?|\.[0-9]+`)

// parseNumber reads the number in "12,010", "$1", "17.8%", "30 basis points", "about 4,000".
func parseNumber(s string) (float64, bool) {
	m := numberCore.FindString(s)
	if m == "" {
		return 0, false
	}
	f, err := strconv.ParseFloat(strings.ReplaceAll(m, ",", ""), 64)
	if err != nil {
		return 0, false
	}
	if i := strings.Index(s, m); i > 0 && s[i-1] == '-' {
		f = -f
	}
	return f, true
}

// decimals: the digits after the point in the number of s.
func decimals(s string) int {
	m := numberCore.FindString(s)
	if i := strings.IndexByte(m, '.'); i >= 0 {
		return len(m) - i - 1
	}
	return 0
}

// compare says whether the stated value holds against the true one.
func compare(kind, comparator, stated, actual string, tolerance float64) (bool, error) {
	if !numericKind(kind) {
		switch comparator {
		case "equal":
			return stated == actual, nil
		case "prefix":
			return len(stated) > 0 && strings.HasPrefix(actual, stated), nil
		}
		return false, fmt.Errorf("unknown comparator %q", comparator)
	}
	s, ok1 := parseNumber(stated)
	a, ok2 := parseNumber(actual)
	if !ok1 {
		return false, fmt.Errorf("the text %q holds no number", stated)
	}
	if !ok2 {
		return false, fmt.Errorf("the command gave %q, which is not a number", actual)
	}
	switch comparator {
	case "equal":
		return math.Abs(s-a) <= 1e-9*math.Max(1, math.Abs(a)), nil
	case "at_least":
		return a >= s, nil
	case "at_most":
		return a <= s, nil
	case "approximately":
		tol := tolerance
		if tol == 0 {
			tol = 0.1
		}
		return math.Abs(a-s) <= tol*math.Abs(a), nil
	case "rounded":
		p := math.Pow(10, float64(decimals(stated)))
		return math.Abs(math.Round(a*p)/p-s) <= 1e-9*math.Max(1, math.Abs(s)), nil
	}
	return false, fmt.Errorf("unknown comparator %q", comparator)
}

// formatLike writes the true value the way the text wrote the old one: its sign, thousands commas, decimals and
// unit stay; for a short hash, as many characters as the text showed.
func formatLike(kind, says, actual string) string {
	if !numericKind(kind) {
		if kind == KindHash && len(says) < len(actual) && len(says) >= 8 {
			return actual[:len(says)]
		}
		return actual
	}
	a, ok := parseNumber(actual)
	m := numberCore.FindStringIndex(says)
	if !ok || m == nil {
		return actual
	}
	core := says[m[0]:m[1]]
	num := strconv.FormatFloat(math.Abs(a), 'f', decimals(says), 64)
	if strings.Contains(core, ",") {
		num = addCommas(num)
	}
	before := says[:m[0]]
	hadMinus := strings.HasSuffix(before, "-")
	switch {
	case a < 0 && !hadMinus:
		before += "-"
	case a >= 0 && hadMinus:
		before = strings.TrimSuffix(before, "-")
	}
	return before + num + says[m[1]:]
}

func addCommas(num string) string {
	intPart, frac, _ := strings.Cut(num, ".")
	var b strings.Builder
	for i, r := range intPart {
		if i > 0 && (len(intPart)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(r)
	}
	if frac != "" {
		return b.String() + "." + frac
	}
	return b.String()
}

// trueValue runs an entry's command and applies its conversion.
func trueValue(root string, e Entry, network bool) (string, error) {
	timeout := 60 * time.Second
	if e.Source == "network" && !network {
		return "", errNetworkOff
	}
	raw, err := runCommand(root, e.Command, network, timeout)
	if err != nil {
		return "", err
	}
	return applyConvert(raw, e.Convert)
}

func cmdValue(args []string) (int, error) {
	root, rest, err := rootFlag(args)
	if err != nil {
		return 2, err
	}
	if len(rest) == 0 {
		return 2, errors.New("give a command, for example: knos-sync value json docs/data/scorecard_summary.json rows")
	}
	v, err := runCommand(root, rest, true, 60*time.Second)
	if err != nil {
		return 2, err
	}
	fmt.Println(v)
	return 0, nil
}

// rootFlag takes a leading --root DIR off args.
func rootFlag(args []string) (string, []string, error) {
	flagValue := ""
	if len(args) >= 2 && args[0] == "--root" {
		flagValue, args = args[1], args[2:]
	} else if len(args) >= 1 && strings.HasPrefix(args[0], "--root=") {
		flagValue, args = strings.TrimPrefix(args[0], "--root="), args[1:]
	}
	root, err := resolveRoot(flagValue)
	return root, args, err
}
