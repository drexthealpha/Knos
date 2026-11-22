//go:build windows

package main

import (
	"syscall"
	"unsafe"
)

// processMemoryCounters is PROCESS_MEMORY_COUNTERS of psapi.h.
type processMemoryCounters struct {
	cb                         uint32
	pageFaultCount             uint32
	peakWorkingSetSize         uintptr
	workingSetSize             uintptr
	quotaPeakPagedPoolUsage    uintptr
	quotaPagedPoolUsage        uintptr
	quotaPeakNonPagedPoolUsage uintptr
	quotaNonPagedPoolUsage     uintptr
	pagefileUsage              uintptr
	peakPagefileUsage          uintptr
}

var procGetProcessMemoryInfo = syscall.NewLazyDLL("psapi.dll").NewProc("GetProcessMemoryInfo")

// peakMemory is the process's peak working set in bytes (GetProcessMemoryInfo); 0 when it cannot be read.
func peakMemory() uint64 {
	h, err := syscall.GetCurrentProcess()
	if err != nil {
		return 0
	}
	var c processMemoryCounters
	c.cb = uint32(unsafe.Sizeof(c))
	if procGetProcessMemoryInfo.Find() != nil {
		return 0
	}
	r, _, _ := procGetProcessMemoryInfo.Call(uintptr(h), uintptr(unsafe.Pointer(&c)), uintptr(c.cb))
	if r == 0 {
		return 0
	}
	return uint64(c.peakWorkingSetSize)
}
