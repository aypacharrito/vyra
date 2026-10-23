package main

import (
	"encoding/binary"
	"testing"
)

func TestWorkerUpgradeRecognizesPreviousRelease(t *testing.T) {
	if !isLegacyClipsVersion("0.6.5") {
		t.Fatal("the previous release must be replaceable during upgrade")
	}
	for _, version := range []string{"", "unknown", "0.6.50", "9.0.0", clipsWorkerVersion} {
		if isLegacyClipsVersion(version) {
			t.Fatalf("unexpected legacy worker match: %q", version)
		}
	}
}

func TestWorkerCommandAcceptsBothShippedLaunchers(t *testing.T) {
	args := []string{`C:\Users\Owner\VYRA\.venv\Scripts\python.exe`, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8765"}
	if !isClipsWorkerCommand(args, 8765) || !isClipsWorkerCommand(append(args, "--no-access-log"), 8765) {
		t.Fatal("must recognize desktop and batch launchers")
	}
	for _, bad := range [][]string{append(args, "--reload"), append([]string{"other.exe"}, args[1:]...), {"python.exe", "server.py"}} {
		if isClipsWorkerCommand(bad, 8765) {
			t.Fatalf("unexpected command accepted: %v", bad)
		}
	}
	if isClipsWorkerCommand(args, 8766) {
		t.Fatal("wrong port accepted")
	}
}

func TestWindowsListenerTableMatchesOnlyExactLoopbackPort(t *testing.T) {
	table := make([]byte, 4+24*2)
	binary.LittleEndian.PutUint32(table, 2)
	for i := 0; i < 2; i++ {
		row := table[4+i*24 : 4+(i+1)*24]
		binary.LittleEndian.PutUint32(row, 2)
		copy(row[4:8], []byte{127, 0, 0, 1})
		binary.BigEndian.PutUint16(row[8:10], uint16(8765+i))
		binary.LittleEndian.PutUint32(row[20:24], uint32(100+i))
	}
	pid, err := workerPIDFromTCPTable(table, 8765)
	if err != nil || pid != 100 {
		t.Fatalf("pid %d, error %v", pid, err)
	}
	copy(table[8:12], []byte{0, 0, 0, 0})
	pid, err = workerPIDFromTCPTable(table, 8765)
	if err != nil || pid != 0 {
		t.Fatal("wildcard/unrelated listener matched")
	}
	if _, err = workerPIDFromTCPTable(table[:10], 8765); err == nil {
		t.Fatal("truncated table accepted")
	}
}
