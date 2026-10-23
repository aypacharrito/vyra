package main

import (
	"strings"
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
	// The script executed on Windows must agree with the launcher's decision.
	script := legacyWorkerStopScript()
	if strings.Contains(script, "__LEGACY_VERSIONS__") {
		t.Fatal("unexpanded script version list")
	}
	for _, version := range legacyClipsVersions {
		if !strings.Contains(script, "'"+version+"'") {
			t.Fatalf("Windows restart script rejects launcher-supported %s", version)
		}
	}
}
