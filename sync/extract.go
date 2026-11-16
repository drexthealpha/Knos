package main

import (
	"regexp"
	"strings"
	"unicode/utf8"
)

// lineText is what a reader sees on one source line: its prose, its code spans and its link targets.
type lineText struct {
	Line  int
	Text  string
	Code  []string
	Links []string
}

// Candidate is one possible fact found by fixed rules (E3). No model reads the text (SYNC/P4.md strongest rule 1).
type Candidate struct {
	File  string `json:"file"`
	Line  int    `json:"line"`
	Kind  string `json:"kind"`
	Value string `json:"value"`
	Text  string `json:"text"`
	State string `json:"state"`
	By    string `json:"by,omitempty"`
}

var (
	reURL  = regexp.MustCompile("https?://[^\\s<>\"'`)\\]]+")
	reDate = regexp.MustCompile(`\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?Z?)?\b` +
		`|\b\d{1,2}:\d{2}(?::\d{2})?\b` +
		`|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?(?:\s+\d{4})?\b` +
		`|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,\s*\d{4})?\b` +
		`|\b(?:19|20)\d{2}\b`)
	rePath    = regexp.MustCompile(`\b[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?:md|py|json|ya?ml|go|js|mjs|ts|html|sh|toml|rs|txt|css|lean|csv|png|svg|wasm)\b`)
	reHash    = regexp.MustCompile(`\b[0-9a-fA-F]{8,64}\b`)
	reVersion = regexp.MustCompile(`\bv?\d+(?:\.\d+){1,3}(?:-[0-9A-Za-z.]+)?\b`)
	rePrice   = regexp.MustCompile(`[$€£¥]\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:million|billion|thousand|[kKmMbB])\b)?` +
		`|\d[\d,]*(?:\.\d+)?\s?%` +
		`|\d[\d,]*(?:\.\d+)?\s+(?:basis points|bps)\b`)
	reCount   = regexp.MustCompile(`\b(\d[\d,]*(?:\.\d+)?)\s+([A-Za-z][A-Za-z-]*)`)
	reTrigger = regexp.MustCompile(`(?i)\b(?:supports?|compatible|works with|faster|fastest|first|only|never|always|guarantee[sd]?)\b`)
	reSecret  = regexp.MustCompile(`(?i)secret|password|passwd|private[ _-]?key|api[ _-]?key|access[ _-]?token|bearer`)
	reSent    = regexp.MustCompile(`[^.!?]+[.!?]*`)
	reHex     = regexp.MustCompile(`^[0-9a-f]{8,64}$|^[0-9A-F]{8,64}$`)
	reVerFull = regexp.MustCompile(`^v?\d+(?:\.\d+){1,2}(?:-[0-9A-Za-z.]+)?$`)
)

// Words that follow a number without making it a count of things.
var notNouns = toSet(`the a an and or of to in on at by for with from as is are was were be been it its this that these
those than then so but not no nor if into onto per via over under about after before up down out off more less most
least times x ms s sec secs kb mb gb tb kib mib gib px pt em rem cm mm km kg g m k am pm utc gmt jan feb mar apr may
jun jul aug sep sept oct nov dec january february march april june july august september october november december`)

// The first word of a code span that makes it a command a reader may run.
var commandWords = toSet(`knos knos-sync python python3 py pip pipx uv uvx git npm npx node bash sh go curl gh cargo near
pytest docker make`)

var versionWords = []string{"version", "versions", "release", "python", "node", "go", "rust", "lean", "knos"}

func toSet(s string) map[string]bool {
	m := map[string]bool{}
	for _, w := range strings.Fields(s) {
		m[w] = true
	}
	return m
}

// extractLine lists the candidates on one line. File and State are set by the caller.
func extractLine(lt lineText) []Candidate {
	var out []Candidate
	text := lt.Text
	hit := make([]bool, len(text))  // bytes that belong to a candidate
	gone := make([]bool, len(text)) // bytes already taken (candidates and dates)
	free := func(a, b int) bool {
		for i := a; i < b; i++ {
			if gone[i] {
				return false
			}
		}
		return true
	}
	take := func(a, b int, candidate bool) {
		for i := a; i < b; i++ {
			gone[i] = true
			if candidate {
				hit[i] = true
			}
		}
	}
	add := func(kind, value string, a, b int) {
		out = append(out, Candidate{Line: lt.Line, Kind: kind, Value: value, Text: snippet(text, a, b)})
		take(a, b, true)
	}

	for _, m := range reURL.FindAllStringIndex(text, -1) {
		v := strings.TrimRight(text[m[0]:m[1]], ".,;:")
		add(KindName, v, m[0], m[0]+len(v))
	}
	for _, m := range rePath.FindAllStringIndex(text, -1) {
		if free(m[0], m[1]) {
			add(KindName, text[m[0]:m[1]], m[0], m[1])
		}
	}
	for _, m := range reHash.FindAllStringIndex(text, -1) {
		v := text[m[0]:m[1]]
		if free(m[0], m[1]) && isHash(v) {
			add(KindHash, v, m[0], m[1])
		}
	}
	for _, m := range reVersion.FindAllStringIndex(text, -1) {
		if !free(m[0], m[1]) {
			continue
		}
		v := text[m[0]:m[1]]
		switch versionShape(text[:m[0]], v) {
		case "version":
			add(KindVersion, v, m[0], m[1])
		case "date", "other":
			take(m[0], m[1], false)
		}
	}
	for _, m := range reDate.FindAllStringIndex(text, -1) {
		if free(m[0], m[1]) {
			take(m[0], m[1], false)
		}
	}
	for _, m := range rePrice.FindAllStringIndex(text, -1) {
		if free(m[0], m[1]) {
			add(KindPrice, strings.TrimSpace(text[m[0]:m[1]]), m[0], m[1])
		}
	}
	for _, m := range reCount.FindAllStringSubmatchIndex(text, -1) {
		numA, numB, wordA, wordB := m[2], m[3], m[4], m[5]
		if !free(numA, numB) {
			continue
		}
		if numA > 0 && (text[numA-1] == '#' || text[numA-1] == '.' || text[numA-1] == '-') {
			continue
		}
		if notNouns[strings.ToLower(text[wordA:wordB])] {
			continue
		}
		add(KindCount, text[numA:numB], numA, wordB)
	}

	// Any other factual sentence: one that holds a digit or a word of comparison, and no candidate.
	for _, m := range reSent.FindAllStringIndex(text, -1) {
		a, b := m[0], m[1]
		s := strings.TrimSpace(text[a:b])
		if len(s) < 20 {
			continue
		}
		covered, digit := false, false
		for i := a; i < b; i++ {
			if hit[i] {
				covered = true
				break
			}
			if !gone[i] && text[i] >= '0' && text[i] <= '9' {
				digit = true
			}
		}
		if covered || !(digit || reTrigger.MatchString(s)) {
			continue
		}
		s = truncate(s, 200)
		out = append(out, Candidate{Line: lt.Line, Kind: KindSentence, Value: s, Text: s})
	}

	for _, c := range lt.Code {
		c = strings.TrimSpace(c)
		if c == "" {
			continue
		}
		first := strings.ToLower(strings.Fields(c)[0])
		switch {
		case commandWords[first]:
			out = append(out, Candidate{Line: lt.Line, Kind: KindName, Value: c, Text: c})
		case reHex.MatchString(strings.TrimRight(c, "…")) && isHash(strings.TrimRight(c, "…")):
			out = append(out, Candidate{Line: lt.Line, Kind: KindHash, Value: strings.TrimRight(c, "…"), Text: c})
		case reVerFull.MatchString(c) && (strings.HasPrefix(c, "v") || strings.Count(c, ".") == 2):
			out = append(out, Candidate{Line: lt.Line, Kind: KindVersion, Value: c, Text: c})
		case len(c) > 1 && !strings.ContainsAny(c, " \t") && (strings.Contains(c, "/") || rePath.MatchString(c)) && !(c[0] >= '0' && c[0] <= '9'):
			out = append(out, Candidate{Line: lt.Line, Kind: KindName, Value: c, Text: c})
		}
	}
	for _, l := range lt.Links {
		l = strings.TrimSpace(l)
		switch {
		case l == "" || strings.HasPrefix(l, "#") || strings.HasPrefix(l, "mailto:") || strings.HasPrefix(l, "javascript:"):
		case strings.HasPrefix(l, "http://") || strings.HasPrefix(l, "https://"):
			out = append(out, Candidate{Line: lt.Line, Kind: KindName, Value: l, Text: l})
		default:
			if i := strings.IndexAny(l, "#?"); i >= 0 {
				l = l[:i]
			}
			if l != "" {
				out = append(out, Candidate{Line: lt.Line, Kind: KindName, Value: l, Text: l})
			}
		}
	}
	return out
}

// isHash: hex with at least one digit and one letter, in one case (a word or a decimal is not a hash).
func isHash(v string) bool {
	hasDigit, hasLetter, lower, upper := false, false, false, false
	for i := 0; i < len(v); i++ {
		c := v[i]
		switch {
		case c >= '0' && c <= '9':
			hasDigit = true
		case c >= 'a' && c <= 'f':
			hasLetter, lower = true, true
		case c >= 'A' && c <= 'F':
			hasLetter, upper = true, true
		default:
			return false
		}
	}
	return hasDigit && hasLetter && !(lower && upper)
}

// versionShape: "version", "date" (2026.11.16), or "other" (a decimal, an address with four parts).
func versionShape(before, v string) string {
	core := strings.SplitN(strings.TrimPrefix(v, "v"), "-", 2)[0]
	parts := strings.Split(core, ".")
	if len(parts) == 4 {
		return "other"
	}
	if strings.HasPrefix(v, "v") {
		return "version"
	}
	if len(parts) == 3 {
		if len(parts[0]) == 4 && (strings.HasPrefix(parts[0], "19") || strings.HasPrefix(parts[0], "20")) {
			return "date"
		}
		return "version"
	}
	words := strings.Fields(strings.ToLower(before))
	if len(words) > 0 {
		last := strings.Trim(words[len(words)-1], "(,:")
		for _, w := range versionWords {
			if last == w {
				return "version"
			}
		}
	}
	return "decimal"
}

func snippet(text string, a, b int) string {
	start, end := a-40, b+40
	if start < 0 {
		start = 0
	}
	if end > len(text) {
		end = len(text)
	}
	for start > 0 && start < len(text) && !isBoundary(text[start]) {
		start++
	}
	for end < len(text) && end > 0 && !isBoundary(text[end-1]) {
		end--
	}
	if start > a {
		start = a
	}
	if end < b {
		end = b
	}
	return strings.TrimSpace(text[start:end])
}

func isBoundary(c byte) bool { return c == ' ' || c == '\t' }

// truncate cuts s to at most n bytes without splitting a character.
func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	for n > 0 && !utf8.RuneStart(s[n]) {
		n--
	}
	return s[:n]
}
