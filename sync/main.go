// Command knos-sync keeps the facts that README.md, docs/ and web/ state true to the command that produces each one.
//
//	knos-sync scan [--list] [--json] [--full]   list every candidate fact of five kinds, and each other factual sentence
//	knos-sync check [--unconfirmed] [--json] [--markdown] [--network] [--reread-wait 60s]
//	                                            run every entry of sync/facts.json; print each stale place with its fix
//	knos-sync report --base base.json --head head.json
//	                                            what a change made stale: the comment a pull request gets
//	knos-sync link ...                          add an entry, only if its command reproduces the stated value
//	knos-sync propose                           unlinked text that states an entry's value: possible copies
//	knos-sync confirm <id>                      a person says the link is right (confirmed_by_person: true)
//	knos-sync silence [--file F] [--reason R] <id>
//	                                            mark a notice "not useful"; counted per kind
//	knos-sync fix [<id>...]                     write the true value into every stale place
//	knos-sync accept <id>                       the text was edited to the true value: record it in sync/facts.json
//	knos-sync value <command...>                print what a command gives, as check reads it
//	knos-sync coverage                          public code names no doc mentions
//	knos-sync hook                              the pre-commit hook: exit 1 when any stated fact is stale
//
// No language model is called, and the network is read only by entries whose source says so (and names with
// --network). Exit code 1 only when a stale entry is of a kind that may block (version, hash or count), its kind
// has "block": true in sync/facts.json, a person confirmed it, and its value is not read from a chain or a clock.
// Exit code 2 on a usage or configuration error.
package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

const usage = `knos-sync: stated facts that stay true

  knos-sync scan [--list] [--json] [--full] [--mem-cap-mib 2048]
  knos-sync check [--unconfirmed] [--json] [--markdown] [--network] [--reread-wait 60s] [--full] [<id>...]
  knos-sync report --base BASE.json --head HEAD.json [--record]
  knos-sync link --id ID --kind KIND --subject TEXT --place FILE:LINE --says VALUE [--text TEXT]
                 [--comparator equal] [--tolerance 0.1] [--convert OPS] [--source repo] -- COMMAND...
  knos-sync link --id ID --place FILE:LINE --says VALUE [--text TEXT]      (one more place for an entry)
  knos-sync propose
  knos-sync confirm <id>
  knos-sync silence [--file FILE] [--reason "not useful"] <id>
  knos-sync fix [<id>...]
  knos-sync accept <id>
  knos-sync value COMMAND...
  knos-sync coverage
  knos-sync hook

Every command takes --root DIR (default: the repository that holds the working folder).
`

func main() {
	os.Exit(run(os.Args[1:]))
}

func run(args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		fmt.Print(usage)
		return 0
	}
	cmd, rest := args[0], args[1:]
	var err error
	code := 0
	switch cmd {
	case "scan":
		code, err = cmdScan(rest)
	case "check":
		code, err = cmdCheck(rest)
	case "report":
		code, err = cmdReport(rest)
	case "link":
		code, err = cmdLink(rest)
	case "propose":
		code, err = cmdPropose(rest)
	case "confirm":
		code, err = cmdConfirm(rest)
	case "silence":
		code, err = cmdSilence(rest)
	case "fix":
		code, err = cmdFix(rest)
	case "accept":
		code, err = cmdAccept(rest)
	case "value":
		code, err = cmdValue(rest)
	case "coverage":
		code, err = cmdCoverage(rest)
	case "hook":
		code, err = cmdHook(rest)
	default:
		fmt.Fprintf(os.Stderr, "knos-sync: I do not know the command %q.\n\n%s", cmd, usage)
		return 2
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "knos-sync %s: %v\n", cmd, err)
		if code == 0 {
			code = 2
		}
	}
	return code
}

// findRoot walks up from dir to the folder that holds sync/facts.json or .git.
func findRoot(dir string) (string, error) {
	abs, err := filepath.Abs(dir)
	if err != nil {
		return "", err
	}
	for d := abs; ; {
		if exists(filepath.Join(d, "sync", "facts.json")) || exists(filepath.Join(d, ".git")) {
			return d, nil
		}
		parent := filepath.Dir(d)
		if parent == d {
			return "", errors.New("no repository found above " + abs + ": pass --root")
		}
		d = parent
	}
}

func resolveRoot(flagValue string) (string, error) {
	if flagValue != "" {
		return filepath.Abs(flagValue)
	}
	wd, err := os.Getwd()
	if err != nil {
		return "", err
	}
	return findRoot(wd)
}

func exists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}
