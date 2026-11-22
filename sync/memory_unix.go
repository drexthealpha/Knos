//go:build linux || darwin || freebsd || netbsd || openbsd

package main

import (
	"runtime"
	"syscall"
)

// peakMemory is the process's peak resident memory in bytes, from getrusage (kilobytes on Linux and the BSDs, bytes
// on macOS); 0 when it cannot be read.
func peakMemory() uint64 {
	var ru syscall.Rusage
	if err := syscall.Getrusage(syscall.RUSAGE_SELF, &ru); err != nil {
		return 0
	}
	if runtime.GOOS == "darwin" {
		return uint64(ru.Maxrss)
	}
	return uint64(ru.Maxrss) * 1024
}
