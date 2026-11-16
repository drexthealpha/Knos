package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"
)

// sync/facts.json is changed by bytes at a known span, never rewritten from a parsed tree (SYNC/P5.md finding 12),
// so a person's layout and every other entry stay as they were.

type member struct {
	key        string
	valueStart int
	valueEnd   int
}

func skipWS(s []byte, i int) int {
	for i < len(s) && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r') {
		i++
	}
	return i
}

// valueEnd returns the offset just past the JSON value that starts at i.
func valueEnd(s []byte, i int) (int, error) {
	if i >= len(s) {
		return 0, errors.New("unexpected end of JSON")
	}
	switch s[i] {
	case '"':
		for j := i + 1; j < len(s); j++ {
			switch s[j] {
			case '\\':
				j++
			case '"':
				return j + 1, nil
			}
		}
		return 0, errors.New("unterminated string")
	case '{', '[':
		depth := 0
		for j := i; j < len(s); j++ {
			switch s[j] {
			case '"':
				end, err := valueEnd(s, j)
				if err != nil {
					return 0, err
				}
				j = end - 1
			case '{', '[':
				depth++
			case '}', ']':
				depth--
				if depth == 0 {
					return j + 1, nil
				}
			}
		}
		return 0, errors.New("unterminated object or array")
	}
	j := i
	for j < len(s) && !strings.ContainsRune(",}] \t\r\n", rune(s[j])) {
		j++
	}
	if j == i {
		return 0, fmt.Errorf("no value at offset %d", i)
	}
	return j, nil
}

func objectMembers(s []byte, i int) ([]member, error) {
	if i >= len(s) || s[i] != '{' {
		return nil, fmt.Errorf("offset %d is not an object", i)
	}
	var out []member
	j := skipWS(s, i+1)
	if j < len(s) && s[j] == '}' {
		return out, nil
	}
	for {
		j = skipWS(s, j)
		kEnd, err := valueEnd(s, j)
		if err != nil {
			return nil, err
		}
		var key string
		if err := json.Unmarshal(s[j:kEnd], &key); err != nil {
			return nil, err
		}
		j = skipWS(s, kEnd)
		if j >= len(s) || s[j] != ':' {
			return nil, fmt.Errorf("no colon after key %q", key)
		}
		j = skipWS(s, j+1)
		vEnd, err := valueEnd(s, j)
		if err != nil {
			return nil, err
		}
		out = append(out, member{key: key, valueStart: j, valueEnd: vEnd})
		j = skipWS(s, vEnd)
		if j < len(s) && s[j] == ',' {
			j++
			continue
		}
		if j < len(s) && s[j] == '}' {
			return out, nil
		}
		return nil, fmt.Errorf("bad object near offset %d", j)
	}
}

func arrayElements(s []byte, i int) ([][2]int, error) {
	if i >= len(s) || s[i] != '[' {
		return nil, fmt.Errorf("offset %d is not an array", i)
	}
	var out [][2]int
	j := skipWS(s, i+1)
	if j < len(s) && s[j] == ']' {
		return out, nil
	}
	for {
		j = skipWS(s, j)
		end, err := valueEnd(s, j)
		if err != nil {
			return nil, err
		}
		out = append(out, [2]int{j, end})
		j = skipWS(s, end)
		if j < len(s) && s[j] == ',' {
			j++
			continue
		}
		if j < len(s) && s[j] == ']' {
			return out, nil
		}
		return nil, fmt.Errorf("bad array near offset %d", j)
	}
}

// findPath gives the span of the value at path. A path element is a key, "[N]" for an array index, or "[id=X]"
// for the array element whose "id" is X.
func findPath(s []byte, path []string) (int, int, error) {
	start := skipWS(s, 0)
	end, err := valueEnd(s, start)
	if err != nil {
		return 0, 0, err
	}
	for _, el := range path {
		switch {
		case strings.HasPrefix(el, "[id=") && strings.HasSuffix(el, "]"):
			want := el[4 : len(el)-1]
			elems, err := arrayElements(s, start)
			if err != nil {
				return 0, 0, err
			}
			found := false
			for _, e := range elems {
				if s[e[0]] != '{' {
					continue
				}
				ms, err := objectMembers(s, e[0])
				if err != nil {
					return 0, 0, err
				}
				for _, m := range ms {
					var id string
					if m.key == "id" && json.Unmarshal(s[m.valueStart:m.valueEnd], &id) == nil && id == want {
						start, end, found = e[0], e[1], true
					}
				}
				if found {
					break
				}
			}
			if !found {
				return 0, 0, fmt.Errorf("no entry with id %q", want)
			}
		case strings.HasPrefix(el, "[") && strings.HasSuffix(el, "]"):
			n, err := strconv.Atoi(el[1 : len(el)-1])
			if err != nil {
				return 0, 0, fmt.Errorf("bad index %q", el)
			}
			elems, err := arrayElements(s, start)
			if err != nil {
				return 0, 0, err
			}
			if n < 0 || n >= len(elems) {
				return 0, 0, fmt.Errorf("index %d is out of range", n)
			}
			start, end = elems[n][0], elems[n][1]
		default:
			ms, err := objectMembers(s, start)
			if err != nil {
				return 0, 0, err
			}
			found := false
			for _, m := range ms {
				if m.key == el {
					start, end, found = m.valueStart, m.valueEnd, true
					break
				}
			}
			if !found {
				return 0, 0, fmt.Errorf("no key %q", el)
			}
		}
	}
	return start, end, nil
}

// setValue replaces the value at path with a JSON literal.
func setValue(s []byte, path []string, literal string) ([]byte, error) {
	a, b, err := findPath(s, path)
	if err != nil {
		return nil, err
	}
	out := make([]byte, 0, len(s)+len(literal))
	out = append(out, s[:a]...)
	out = append(out, literal...)
	return append(out, s[b:]...), nil
}

func jsonLiteral(v any) string {
	b, err := encodeJSON(v, "")
	if err != nil {
		return "null"
	}
	return string(b)
}

// lineIndent is the run of spaces that starts the line holding offset i.
func lineIndent(s []byte, i int) string {
	j := i
	for j > 0 && s[j-1] != '\n' {
		j--
	}
	k := j
	for k < len(s) && (s[k] == ' ' || s[k] == '\t') {
		k++
	}
	return string(s[j:k])
}

// appendItem adds v at the end of the array at path, indented like its neighbours.
func appendItem(s []byte, path []string, v any) ([]byte, error) {
	a, b, err := findPath(s, path)
	if err != nil {
		return nil, err
	}
	if string(s[a:b]) == "null" {
		if s, err = setValue(s, path, "[]"); err != nil {
			return nil, err
		}
		b = a + 2
	}
	elems, err := arrayElements(s, a)
	if err != nil {
		return nil, err
	}
	base := lineIndent(s, a)
	indent := base + " "
	if len(elems) > 0 {
		indent = lineIndent(s, elems[0][0])
	}
	item, err := encodeJSON(v, indent)
	if err != nil {
		return nil, err
	}
	var out []byte
	if len(elems) == 0 {
		out = append(out, s[:a]...)
		out = append(out, "[\n"+indent...)
		out = append(out, item...)
		out = append(out, "\n"+base+"]"...)
		return append(out, s[b:]...), nil
	}
	last := elems[len(elems)-1][1]
	out = append(out, s[:last]...)
	out = append(out, ",\n"+indent...)
	out = append(out, item...)
	return append(out, s[last:]...), nil
}

// bumpCount adds one to a whole-number field.
func bumpCount(s []byte, path []string) ([]byte, error) {
	a, b, err := findPath(s, path)
	if err != nil {
		return nil, err
	}
	n, err := strconv.Atoi(string(s[a:b]))
	if err != nil {
		return nil, fmt.Errorf("%s is not a whole number", strings.Join(path, "."))
	}
	return setValue(s, path, strconv.Itoa(n+1))
}
