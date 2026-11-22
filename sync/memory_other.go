//go:build !(linux || darwin || freebsd || netbsd || openbsd || windows)

package main

// peakMemory cannot be read on this system.
func peakMemory() uint64 { return 0 }
