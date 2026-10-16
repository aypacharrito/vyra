package main

import (
	"archive/zip"
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func testMediaZip(t *testing.T, entries map[string]string) string {
	t.Helper()
	name := filepath.Join(t.TempDir(), "engine.zip")
	f, err := os.Create(name)
	if err != nil {
		t.Fatal(err)
	}
	z := zip.NewWriter(f)
	for name, content := range entries {
		out, err := z.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		out.Write([]byte(content))
	}
	z.Close()
	f.Close()
	return name
}
func TestMediaArchiveRequiresBothToolsAndRejectsTraversal(t *testing.T) {
	for _, entries := range []map[string]string{{"engine/bin/ffmpeg.exe": "stub"}, {"../outside": "bad", "engine/bin/ffmpeg.exe": "stub", "engine/bin/ffprobe.exe": "stub"}} {
		if extractMediaArchive(testMediaZip(t, entries), t.TempDir()) == nil {
			t.Fatal("Accepted an incomplete or unsafe engine archive")
		}
	}
	destination := t.TempDir()
	archive := testMediaZip(t, map[string]string{"engine/bin/ffmpeg.exe": "one", "engine/bin/ffprobe.exe": "two", "engine/LICENSE": "notice"})
	if err := extractMediaArchive(archive, destination); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"bin/ffmpeg.exe", "bin/ffprobe.exe", "LICENSE", "BUILD_SOURCE.txt"} {
		if _, err := os.Stat(filepath.Join(destination, name)); err != nil {
			t.Fatal(err)
		}
	}
}
func TestInstallVerifiedVideoEngine(t *testing.T) {
	if os.Getenv("VYRA_MEDIA_SMOKE") != "1" {
		t.Skip("explicit installation integration check")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Minute)
	defer cancel()
	if err := ensureMediaTools(ctx, func(message string) { t.Log(message) }); err != nil {
		t.Fatal(err)
	}
	a, b, ready := mediaPaths()
	if !ready {
		t.Fatal("Engine still missing")
	}
	if err := verifyMedia(ctx, a, b); err != nil {
		t.Fatal(err)
	}
}
