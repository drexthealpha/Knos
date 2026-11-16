package main

import (
	"bytes"
	"sort"
	"strings"

	"github.com/yuin/goldmark"
	"github.com/yuin/goldmark/ast"
	"github.com/yuin/goldmark/text"
)

// lineIndex turns a byte offset into a 1-based line number.
type lineIndex []int

func newLineIndex(src []byte) lineIndex {
	idx := lineIndex{0}
	for i, c := range src {
		if c == '\n' {
			idx = append(idx, i+1)
		}
	}
	return idx
}

func (idx lineIndex) line(pos int) int {
	return sort.Search(len(idx), func(i int) bool { return idx[i] > pos })
}

// markdownLines reads Markdown with a CommonMark parser that keeps byte offsets (SYNC/P5.md finding 10: goldmark;
// CHECKED-P4-P6.md P5-10: v1 chosen on purpose, v1.8.7, whose import path is github.com/yuin/goldmark). Code blocks
// and raw HTML are examples and markup, not prose, and are not read; code spans are kept apart for names.
func markdownLines(src []byte) []lineText {
	idx := newLineIndex(src)
	doc := goldmark.New().Parser().Parse(text.NewReader(src))
	byLine := map[int]*lineText{}
	get := func(pos int) *lineText {
		n := idx.line(pos)
		lt, ok := byLine[n]
		if !ok {
			lt = &lineText{Line: n}
			byLine[n] = lt
		}
		return lt
	}
	_ = ast.Walk(doc, func(n ast.Node, entering bool) (ast.WalkStatus, error) {
		if !entering {
			return ast.WalkContinue, nil
		}
		switch n.Kind() {
		case ast.KindFencedCodeBlock, ast.KindCodeBlock, ast.KindHTMLBlock, ast.KindRawHTML, ast.KindLinkReferenceDefinition:
			return ast.WalkSkipChildren, nil
		case ast.KindCodeSpan:
			var b []byte
			first := -1
			for c := n.FirstChild(); c != nil; c = c.NextSibling() {
				if t, ok := c.(*ast.Text); ok {
					if first < 0 {
						first = t.Segment.Start
					}
					b = append(b, t.Segment.Value(src)...)
				}
			}
			if first >= 0 {
				lt := get(first)
				lt.Code = append(lt.Code, strings.TrimSpace(string(b)))
			}
			return ast.WalkSkipChildren, nil
		case ast.KindLink:
			dest := n.(*ast.Link).Destination
			if pos := posNear(src, n, dest); pos >= 0 {
				lt := get(pos)
				lt.Links = append(lt.Links, string(dest))
			}
		case ast.KindImage:
			dest := n.(*ast.Image).Destination
			if pos := posNear(src, n, dest); pos >= 0 {
				lt := get(pos)
				lt.Links = append(lt.Links, string(dest))
			}
		case ast.KindAutoLink:
			al := n.(*ast.AutoLink)
			if al.AutoLinkType == ast.AutoLinkURL {
				u := al.URL(src)
				if pos := posNear(src, n, u); pos >= 0 {
					lt := get(pos)
					lt.Links = append(lt.Links, string(u))
				}
			}
			return ast.WalkSkipChildren, nil
		case ast.KindText:
			t := n.(*ast.Text)
			if t.Segment.Stop > t.Segment.Start {
				v := strings.ReplaceAll(string(t.Segment.Value(src)), "\n", " ")
				lt := get(t.Segment.Start)
				lt.Text += v
			}
		}
		return ast.WalkContinue, nil
	})
	out := make([]lineText, 0, len(byLine))
	for _, lt := range byLine {
		out = append(out, *lt)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Line < out[j].Line })
	return out
}

// posOf: the node's own offset, else its first text child's, else its nearest block's.
func posOf(n ast.Node) int {
	if p := n.Pos(); p >= 0 {
		return p
	}
	for c := n.FirstChild(); c != nil; c = c.NextSibling() {
		if t, ok := c.(*ast.Text); ok {
			return t.Segment.Start
		}
	}
	for p := n.Parent(); p != nil; p = p.Parent() {
		if pos := p.Pos(); pos >= 0 {
			return pos
		}
	}
	return -1
}

// posNear: where needle (a link's target) stands in the source at or after the node's offset; HTML-like nodes
// have no source position of their own (SYNC/P5.md finding 13), so the target text is looked for.
func posNear(src []byte, n ast.Node, needle []byte) int {
	base := posOf(n)
	if base < 0 {
		base = 0
	}
	if len(needle) > 0 && base < len(src) {
		if i := bytes.Index(src[base:], needle); i >= 0 {
			return base + i
		}
	}
	if p := posOf(n); p >= 0 {
		return p
	}
	return -1
}
