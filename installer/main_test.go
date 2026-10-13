//go:build windows

package main

import (
	"archive/zip"
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestPayloadContainsRealAppAndNoPrivateData(t *testing.T) {
	raw, err := payload()
	if err != nil {
		t.Fatal(err)
	}
	archive, err := zip.NewReader(bytes.NewReader(raw), int64(len(raw)))
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, f := range archive.File {
		name := strings.ToLower(filepath.ToSlash(f.Name))
		for _, bad := range []string{".env", ".local/", "api-key", "queue.sqlite", ".venv/", "__pycache__"} {
			if strings.Contains(name, bad) {
				t.Fatalf("Private data in payload: %s", name)
			}
		}
		if name == "vyra.exe" {
			found = true
			r, err := f.Open()
			if err != nil {
				t.Fatal(err)
			}
			header := make([]byte, 2)
			_, err = r.Read(header)
			r.Close()
			if err != nil || string(header) != "MZ" {
				t.Fatal("Missing Windows executable header")
			}
		}
	}
	if !found {
		t.Fatal("Desktop executable missing")
	}
}
func TestPayloadExtractsWithinSelectedFolder(t *testing.T) {
	dir := t.TempDir()
	if err := extract(dir); err != nil {
		t.Fatal(err)
	}
	for _, file := range []string{"VYRA.exe", "SETUP_CLIPS.bat", "clips-worker/server.py"} {
		if _, err := os.Stat(filepath.Join(dir, filepath.FromSlash(file))); err != nil {
			t.Fatal(file, err)
		}
	}
}
