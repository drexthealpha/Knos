package main

import (
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"time"

	_ "modernc.org/sqlite" // SQLite without a C compiler (CHECKED-P4-P6.md P5 stack table: modernc.org/sqlite v1.62.0)
)

// StatePath is the one working-state file (E2). It is listed in .gitignore and never committed (SYNC/P1.md
// finding 20); CI builds it again on every run and never trusts an old one (SYNC/P5.md finding 20).
const StatePath = ".knos-sync/state.db"

const schema = `
CREATE TABLE IF NOT EXISTS files(
  path TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL,
  size INTEGER NOT NULL,
  seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates(
  path TEXT NOT NULL,
  line INTEGER NOT NULL,
  kind TEXT NOT NULL,
  value TEXT NOT NULL,
  text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS candidates_path ON candidates(path);
CREATE TABLE IF NOT EXISTS observed(
  entry TEXT NOT NULL,
  actual TEXT NOT NULL,
  source TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS failures(
  entry TEXT NOT NULL,
  file TEXT NOT NULL,
  stated TEXT NOT NULL,
  actual TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY(entry, file, stated, actual)
);
`

// State is the SQLite working state: file hashes, the candidates found in each file, the last value each entry's
// command gave (with its time: SYNC/P2.md where wrong 4), and the commit where a stale place was first seen
// (SYNC/P2.md finding 2).
type State struct {
	db *sql.DB
}

func openState(root string) (*State, error) {
	p := filepath.Join(root, filepath.FromSlash(StatePath))
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite", p)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	// Pragmas answer with a row or with none; their answer is not needed, and a database that refuses one still works.
	for _, p := range []string{"PRAGMA busy_timeout = 5000", "PRAGMA journal_mode = WAL", "PRAGMA synchronous = NORMAL"} {
		var v any
		_ = db.QueryRow(p).Scan(&v)
	}
	for _, stmt := range strings.Split(schema, ";") {
		if strings.TrimSpace(stmt) == "" {
			continue
		}
		if _, err := db.Exec(stmt); err != nil {
			db.Close()
			return nil, err
		}
	}
	return &State{db: db}, nil
}

func (s *State) Close() error {
	if s == nil {
		return nil
	}
	return s.db.Close()
}

func now() string { return time.Now().UTC().Format(time.RFC3339) }

// fileHash is the stored content hash of a file, if any.
func (s *State) fileHash(path string) (string, bool) {
	if s == nil {
		return "", false
	}
	var sha string
	if err := s.db.QueryRow(`SELECT sha256 FROM files WHERE path = ?`, path).Scan(&sha); err != nil {
		return "", false
	}
	return sha, true
}

func (s *State) cachedCandidates(path string) ([]Candidate, error) {
	rows, err := s.db.Query(`SELECT line, kind, value, text FROM candidates WHERE path = ? ORDER BY rowid`, path)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Candidate
	for rows.Next() {
		c := Candidate{File: path}
		if err := rows.Scan(&c.Line, &c.Kind, &c.Value, &c.Text); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// storeFile keeps a file's hash and its candidates, in one transaction.
func (s *State) storeFile(path, sha string, size int, cands []Candidate) error {
	if s == nil {
		return nil
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback() //nolint:errcheck // a no-op after Commit
	if _, err := tx.Exec(`DELETE FROM candidates WHERE path = ?`, path); err != nil {
		return err
	}
	for _, c := range cands {
		if _, err := tx.Exec(`INSERT INTO candidates(path, line, kind, value, text) VALUES(?, ?, ?, ?, ?)`,
			path, c.Line, c.Kind, c.Value, c.Text); err != nil {
			return err
		}
	}
	if _, err := tx.Exec(`INSERT INTO files(path, sha256, size, seen) VALUES(?, ?, ?, ?)
		ON CONFLICT(path) DO UPDATE SET sha256 = excluded.sha256, size = excluded.size, seen = excluded.seen`,
		path, sha, size, now()); err != nil {
		return err
	}
	return tx.Commit()
}

// forget drops files that are gone.
func (s *State) forget(keep map[string]bool) error {
	if s == nil {
		return nil
	}
	rows, err := s.db.Query(`SELECT path FROM files`)
	if err != nil {
		return err
	}
	var gone []string
	for rows.Next() {
		var p string
		if err := rows.Scan(&p); err != nil {
			rows.Close()
			return err
		}
		if !keep[p] {
			gone = append(gone, p)
		}
	}
	rows.Close()
	for _, p := range gone {
		if _, err := s.db.Exec(`DELETE FROM files WHERE path = ?`, p); err != nil {
			return err
		}
		if _, err := s.db.Exec(`DELETE FROM candidates WHERE path = ?`, p); err != nil {
			return err
		}
	}
	return nil
}

func (s *State) recordValue(entry, actual, source string) {
	if s == nil {
		return
	}
	_, _ = s.db.Exec(`INSERT INTO observed(entry, actual, source, at) VALUES(?, ?, ?, ?)`, entry, actual, source, now())
}

// firstFailure keeps the commit where this stale place was first seen and returns it.
func (s *State) firstFailure(entry, file, stated, actual, commit string) string {
	if s == nil {
		return commit
	}
	_, _ = s.db.Exec(`INSERT OR IGNORE INTO failures(entry, file, stated, actual, commit_sha, at) VALUES(?, ?, ?, ?, ?, ?)`,
		entry, file, stated, actual, commit, now())
	var first string
	if err := s.db.QueryRow(`SELECT commit_sha FROM failures WHERE entry = ? AND file = ? AND stated = ? AND actual = ?`,
		entry, file, stated, actual).Scan(&first); err != nil {
		return commit
	}
	return first
}
