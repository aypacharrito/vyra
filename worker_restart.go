package main

import (
	"encoding/binary"
	"errors"
	"strconv"
	"strings"
)

// Both the launcher and Windows replacement check use this list. Keeping a
// second hard-coded list caused upgrades from 0.6.5 to fail on Windows.
var legacyClipsVersions = []string{"0.3.0", "0.4.0", "0.5.0", "0.6.0", "0.6.1", "0.6.2", "0.6.3", "0.6.4", "0.6.5", "0.6.6"}

func isLegacyClipsVersion(version string) bool {
	for _, known := range legacyClipsVersions {
		if version == known {
			return true
		}
	}
	return false
}

// Decode MIB_TCPTABLE_OWNER_PID with strict bounds and a loopback-only match.
func workerPIDFromTCPTable(table []byte, port int) (uint32, error) {
	if len(table) < 4 {
		return 0, errors.New("Truncated Windows listener table")
	}
	count := uint64(binary.LittleEndian.Uint32(table[:4]))
	if count > uint64((len(table)-4)/24) {
		return 0, errors.New("Truncated Windows listener rows")
	}
	var owner uint32
	for i := uint64(0); i < count; i++ {
		row := table[4+i*24 : 4+(i+1)*24]
		if binary.LittleEndian.Uint32(row[:4]) != 2 || string(row[4:8]) != string([]byte{127, 0, 0, 1}) || int(binary.BigEndian.Uint16(row[8:10])) != port {
			continue
		}
		pid := binary.LittleEndian.Uint32(row[20:24])
		if pid == 0 {
			return 0, errors.New("Invalid Clips listener owner")
		}
		if owner != 0 && owner != pid {
			return 0, errors.New("Multiple processes own the Clips address")
		}
		owner = pid
	}
	return owner, nil
}

func isClipsWorkerCommand(args []string, port int) bool {
	if len(args) != 8 && len(args) != 9 {
		return false
	}
	// Windows Python and its venv redirector quote arguments differently.
	exe := strings.ToLower(strings.ReplaceAll(args[0], "\\", "/"))
	exe = exe[strings.LastIndex(exe, "/")+1:]
	if exe != "python.exe" && exe != "pythonw.exe" {
		return false
	}
	expected := []string{"-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", strconv.Itoa(port)}
	for i, value := range expected {
		if args[i+1] != value {
			return false
		}
	}
	return len(args) == 8 || args[8] == "--no-access-log"
}
