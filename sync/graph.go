package main

import (
	"bytes"
	"compress/zlib"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"path/filepath"
	"sort"
	"strings"
)

// The graph (L56) lives in the state file: nodes are files, entries and code names; an edge points from what
// depends to what it depends on (PROV's wasDerivedFrom direction, SYNC/P4.md), with a confidence and a source tag
// (SYNC/P3.md: static and recorded information kept apart by tag). Indexes on both edge directions (SYNC/P5.md).
const (
	NodeFile  = "file"
	NodeEntry = "entry"
	NodeName  = "name"

	EdgeDerived = "wasDerivedFrom" // a doc's text comes from an entry; an entry's value from a file
	EdgeDefined = "definedIn"      // a code name is defined in a file
	EdgeMention = "mentions"       // a doc names a code name

	SourceFacts  = "facts"  // a link a person or knos-sync link wrote in sync/facts.json
	SourceStatic = "static" // read from the code by fixed patterns
)

// dbtx is a database or a transaction.
type dbtx interface {
	Exec(query string, args ...any) (sql.Result, error)
	QueryRow(query string, args ...any) *sql.Row
}

// addNode returns a node's id, adding the node when it is new; a node keeps a span (file, lines), never a text copy.
func addNode(q dbtx, kind, key, file string, start, end int) (int64, error) {
	if _, err := q.Exec(`INSERT INTO nodes(kind, key, file, start_line, end_line) VALUES(?, ?, ?, ?, ?)
		ON CONFLICT(kind, key) DO UPDATE SET file = excluded.file, start_line = excluded.start_line, end_line = excluded.end_line`,
		kind, key, file, start, end); err != nil {
		return 0, err
	}
	var id int64
	err := q.QueryRow(`SELECT id FROM nodes WHERE kind = ? AND key = ?`, kind, key).Scan(&id)
	return id, err
}

func addEdge(q dbtx, src, dst int64, kind string, confidence float64, source string) error {
	_, err := q.Exec(`INSERT INTO edges(src, dst, kind, confidence, source) VALUES(?, ?, ?, ?, ?)
		ON CONFLICT(src, dst, kind) DO UPDATE SET confidence = excluded.confidence, source = excluded.source`,
		src, dst, kind, confidence, source)
	return err
}

// commandFile is the file an entry's command reads, or "" for a program, a folder count or the network.
func commandFile(e Entry) string {
	if len(e.Command) < 2 {
		return ""
	}
	switch e.Command[0] {
	case "json", "regex", "count-lines", "sha256", "size", "exists":
		return e.Command[1]
	}
	return ""
}

// storeFactsGraph writes the links of sync/facts.json: each doc file that states an entry depends on it, and the
// entry depends on the file its command reads. The confidence is 1 when a person confirmed the link, else 1/n where
// n entries share its expected value: which thing a number is about is its own, uncertain step (SYNC/P4.md).
func (s *State) storeFactsGraph(c *Facts) error {
	if s == nil {
		return nil
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback() //nolint:errcheck // a no-op after Commit
	if _, err := tx.Exec(`DELETE FROM edges WHERE source = ?`, SourceFacts); err != nil {
		return err
	}
	same := map[string]int{}
	for _, e := range c.Entries {
		same[normValue(e.Expected)]++
	}
	for _, e := range c.Entries {
		conf := 1.0
		if !e.ConfirmedByPerson {
			conf = 1 / float64(same[normValue(e.Expected)])
		}
		en, err := addNode(tx, NodeEntry, e.ID, "", 0, 0)
		if err != nil {
			return err
		}
		for _, p := range e.Places {
			fn, err := addNode(tx, NodeFile, p.File, p.File, 0, 0)
			if err != nil {
				return err
			}
			if err := addEdge(tx, fn, en, EdgeDerived, conf, SourceFacts); err != nil {
				return err
			}
		}
		if src := commandFile(e); src != "" {
			fn, err := addNode(tx, NodeFile, src, src, 0, 0)
			if err != nil {
				return err
			}
			if err := addEdge(tx, en, fn, EdgeDerived, conf, SourceFacts); err != nil {
				return err
			}
		}
	}
	return tx.Commit()
}

// storeNameGraph writes the name-reference graph (SYNC/P3.md: names, not calls): a doc depends on each code name it
// mentions, and the name on the file that defines it. Only names a doc mentions get nodes. The confidence is 1/n
// where n definitions share the name.
func (s *State) storeNameGraph(defs []CodeName, mentions []nameMention, index map[string]int) error {
	if s == nil {
		return nil
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback() //nolint:errcheck // a no-op after Commit
	if _, err := tx.Exec(`DELETE FROM edges WHERE source = ?`, SourceStatic); err != nil {
		return err
	}
	wanted := map[string]bool{}
	for _, m := range mentions {
		wanted[m.name] = true
	}
	nodesOf := map[string][]int64{}
	for _, d := range defs {
		if !wanted[d.Name] {
			continue
		}
		id, err := addNode(tx, NodeName, d.File+"#"+d.Name, d.File, d.Line, d.Line)
		if err != nil {
			return err
		}
		fn, err := addNode(tx, NodeFile, d.File, d.File, 0, 0)
		if err != nil {
			return err
		}
		if err := addEdge(tx, id, fn, EdgeDefined, 1, SourceStatic); err != nil {
			return err
		}
		nodesOf[d.Name] = append(nodesOf[d.Name], id)
	}
	for _, m := range mentions {
		doc, err := addNode(tx, NodeFile, m.doc, m.doc, 0, 0)
		if err != nil {
			return err
		}
		for _, id := range nodesOf[m.name] {
			if err := addEdge(tx, doc, id, EdgeMention, 1/float64(index[m.name]), SourceStatic); err != nil {
				return err
			}
		}
	}
	return tx.Commit()
}

// Affected is one node a change reaches, with its hop distance (SYNC/P3.md: nearest first).
type Affected struct {
	Kind string `json:"kind"`
	Key  string `json:"key"`
	Hops int    `json:"hops"`
}

// affected walks from changed files to everything that depends on them, nearest first, at most maxHops away.
func (s *State) affected(files []string, maxHops int) ([]Affected, error) {
	if s == nil {
		return nil, nil
	}
	type item struct {
		id   int64
		hops int
	}
	seen := map[int64]bool{}
	var queue []item
	for _, f := range files {
		var id int64
		if err := s.db.QueryRow(`SELECT id FROM nodes WHERE kind = ? AND key = ?`, NodeFile, f).Scan(&id); err == nil {
			seen[id] = true
			queue = append(queue, item{id, 0})
		}
	}
	var out []Affected
	for len(queue) > 0 {
		it := queue[0]
		queue = queue[1:]
		if it.hops >= maxHops {
			continue
		}
		rows, err := s.db.Query(`SELECT n.id, n.kind, n.key FROM edges e JOIN nodes n ON n.id = e.src WHERE e.dst = ? ORDER BY n.id`, it.id)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var id int64
			a := Affected{Hops: it.hops + 1}
			if err := rows.Scan(&id, &a.Kind, &a.Key); err != nil {
				rows.Close()
				return nil, err
			}
			if seen[id] {
				continue
			}
			seen[id] = true
			out = append(out, a)
			queue = append(queue, item{id, a.Hops})
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return nil, err
		}
	}
	return out, nil
}

// compress keeps a file's content once, as a zlib blob keyed by its hash (SYNC/P5.md: blobs in SQLite, spans on
// nodes).
func compress(b []byte) ([]byte, error) {
	var buf bytes.Buffer
	w := zlib.NewWriter(&buf)
	if _, err := w.Write(b); err != nil {
		return nil, err
	}
	if err := w.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// blob gives back a stored file content by its hash.
func (s *State) blob(sha string) ([]byte, error) {
	var data []byte
	if err := s.db.QueryRow(`SELECT data FROM blobs WHERE sha256 = ?`, sha).Scan(&data); err != nil {
		return nil, err
	}
	r, err := zlib.NewReader(bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	defer r.Close()
	return io.ReadAll(r)
}

// trace is what an entry's last check read, each input with its hash, and the result it gave (a verifying trace,
// SYNC/P3.md).
func (s *State) trace(entry string) (string, string, bool) {
	if s == nil {
		return "", "", false
	}
	var inputs, result string
	if err := s.db.QueryRow(`SELECT inputs, result FROM traces WHERE entry = ?`, entry).Scan(&inputs, &result); err != nil {
		return "", "", false
	}
	return inputs, result, true
}

func (s *State) storeTrace(entry, inputs, result string) {
	if s == nil {
		return
	}
	_, _ = s.db.Exec(`INSERT INTO traces(entry, inputs, result) VALUES(?, ?, ?)
		ON CONFLICT(entry) DO UPDATE SET inputs = excluded.inputs, result = excluded.result`, entry, inputs, result)
}

// inputsOf lists what an entry's check reads, each with its hash. ok is false for an entry that runs again every
// time: a value from a chain, a clock or the network (volatile, SYNC/P4.md), a program, or a folder count.
func inputsOf(fc *fileCache, c *Facts, e Entry) (string, bool) {
	if e.volatile() || commandFile(e) == "" {
		return "", false
	}
	var silences []Silence
	for _, s := range c.Silenced {
		if s.ID == e.ID {
			silences = append(silences, s)
		}
	}
	def, err := json.Marshal(struct {
		Entry    Entry
		Kind     *KindSetting
		Silenced []Silence
	}{e, c.Kinds[e.Kind], silences})
	if err != nil {
		return "", false
	}
	sum := sha256.Sum256(def)
	lines := []string{"facts " + hex.EncodeToString(sum[:])}
	files := make([]string, 0, len(e.Places)+1)
	for _, p := range e.Places {
		files = append(files, p.File)
	}
	if e.Command[0] == "exists" {
		lines = append(lines, fmt.Sprintf("exists %s %t", e.Command[1], exists(filepath.Join(fc.root, filepath.FromSlash(e.Command[1])))))
	} else {
		files = append(files, e.Command[1])
	}
	for _, f := range files {
		h := "missing"
		if _, err := fc.get(f); err == nil {
			h = fc.hashes[f]
		}
		lines = append(lines, "file "+f+" "+h)
	}
	sort.Strings(lines)
	return strings.Join(lines, "\n"), true
}
