package main

import (
	"bytes"
	"sort"
	"strings"
)

var entities = map[string]string{
	"amp": "&", "lt": "<", "gt": ">", "quot": `"`, "apos": "'", "#39": "'", "nbsp": " ", "#160": " ",
	"mdash": "-", "ndash": "-", "hellip": "...", "rsquo": "'", "lsquo": "'", "rdquo": `"`, "ldquo": `"`,
	"times": "x", "euro": "€", "pound": "£", "yen": "¥", "#36": "$", "middot": " ",
}

// Tags whose start or end separates words.
var blockTags = toSet(`p div br li ul ol td th tr table h1 h2 h3 h4 h5 h6 section article header footer nav main aside
details summary dd dt dl figure figcaption blockquote hr button label option select form`)

// htmlLines gives the visible text of an HTML page by line: no scripts, styles, comments or head; <code> and <pre>
// apart as code; href targets as links. Every piece keeps the line it starts on.
func htmlLines(src []byte) []lineText {
	byLine := map[int]*lineText{}
	texts := map[int]*strings.Builder{}
	write := func(n int, piece string) {
		b, ok := texts[n]
		if !ok {
			b = &strings.Builder{}
			texts[n] = b
			get0(byLine, n)
		}
		b.WriteString(piece)
	}
	get := func(n int) *lineText { return get0(byLine, n) }
	line := 1
	inHead, codeDepth := false, 0
	var code strings.Builder
	codeLine := 0
	advance := func(from, to int) { // count the newlines skipped
		line += bytes.Count(src[from:to], []byte{'\n'})
	}
	lower := asciiLower(src)
	i := 0
	for i < len(src) {
		c := src[i]
		switch {
		case bytes.HasPrefix(src[i:], []byte("<!--")):
			end := bytes.Index(src[i+4:], []byte("-->"))
			stop := len(src)
			if end >= 0 {
				stop = i + 4 + end + 3
			}
			advance(i, stop)
			i = stop
		case c == '<' && i+1 < len(src) && (isLetter(src[i+1]) || src[i+1] == '/' || src[i+1] == '!'):
			stop := tagEnd(src, i)
			tag := src[i:stop]
			name, closing := tagName(tag)
			tagLine := line
			advance(i, stop)
			i = stop
			switch {
			case (name == "script" || name == "style") && !closing:
				end := bytes.Index(lower[i:], []byte("</"+name))
				skip := len(src)
				if end >= 0 {
					skip = i + end
				}
				advance(i, skip)
				i = skip
			case name == "head":
				inHead = !closing
			case name == "code" || name == "pre":
				if !closing {
					if codeDepth == 0 {
						code.Reset()
						codeLine = line
					}
					codeDepth++
				} else if codeDepth > 0 {
					codeDepth--
					if codeDepth == 0 && strings.TrimSpace(code.String()) != "" {
						lt := get(codeLine)
						lt.Code = append(lt.Code, strings.TrimSpace(code.String()))
					}
				}
			case name == "a" && !closing:
				if href := attr(tag, "href"); href != "" {
					lt := get(tagLine)
					lt.Links = append(lt.Links, href)
				}
			}
			if blockTags[name] && !inHead && codeDepth == 0 {
				write(line, " ")
			}
		default:
			var piece string
			if c == '&' {
				end := bytes.IndexByte(src[i:min(i+12, len(src))], ';')
				if end > 1 {
					if v, ok := entities[string(src[i+1:i+end])]; ok {
						piece = v
						i += end + 1
					}
				}
			}
			if piece == "" {
				if c == '\n' {
					line++
					i++
					if codeDepth > 0 {
						code.WriteByte(' ')
					}
					continue
				}
				piece = string(src[i : i+1])
				i++
			}
			if inHead {
				continue
			}
			if codeDepth > 0 {
				code.WriteString(piece)
			} else {
				write(line, piece)
			}
		}
	}
	out := make([]lineText, 0, len(byLine))
	for n, lt := range byLine {
		if b, ok := texts[n]; ok {
			lt.Text = b.String()
		}
		out = append(out, *lt)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Line < out[j].Line })
	return out
}

// get0 makes sure a line has an entry.
func get0(byLine map[int]*lineText, n int) *lineText {
	lt, ok := byLine[n]
	if !ok {
		lt = &lineText{Line: n}
		byLine[n] = lt
	}
	return lt
}

// asciiLower lowers A to Z only, so every offset stays the same.
func asciiLower(src []byte) []byte {
	out := make([]byte, len(src))
	for i, c := range src {
		if c >= 'A' && c <= 'Z' {
			c += 'a' - 'A'
		}
		out[i] = c
	}
	return out
}

func isLetter(c byte) bool { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') }

// tagEnd: the offset just past the tag that starts at i, quotes respected.
func tagEnd(src []byte, i int) int {
	var quote byte
	for j := i + 1; j < len(src); j++ {
		switch c := src[j]; {
		case quote != 0:
			if c == quote {
				quote = 0
			}
		case c == '"' || c == '\'':
			quote = c
		case c == '>':
			return j + 1
		}
	}
	return len(src)
}

func tagName(tag []byte) (string, bool) {
	t := strings.TrimPrefix(string(tag), "<")
	closing := strings.HasPrefix(t, "/")
	t = strings.TrimPrefix(t, "/")
	end := strings.IndexAny(t, " \t\r\n/>")
	if end < 0 {
		end = len(t)
	}
	return strings.ToLower(t[:end]), closing
}

// attr reads one attribute's value from a tag.
func attr(tag []byte, name string) string {
	s := string(tag)
	low := strings.ToLower(s)
	for from := 0; ; {
		k := strings.Index(low[from:], name)
		if k < 0 {
			return ""
		}
		k += from
		from = k + len(name)
		if k > 0 && !strings.ContainsRune(" \t\r\n", rune(low[k-1])) {
			continue
		}
		rest := strings.TrimLeft(s[from:], " \t\r\n")
		if !strings.HasPrefix(rest, "=") {
			continue
		}
		rest = strings.TrimLeft(rest[1:], " \t\r\n")
		if rest == "" {
			return ""
		}
		if q := rest[0]; q == '"' || q == '\'' {
			if end := strings.IndexByte(rest[1:], q); end >= 0 {
				return rest[1 : 1+end]
			}
			return ""
		}
		end := strings.IndexAny(rest, " \t\r\n>")
		if end < 0 {
			end = len(rest)
		}
		return rest[:end]
	}
}
