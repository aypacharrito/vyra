package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSetupUsesHealthyPrivatePythonWithoutGlobalPython(t *testing.T) {
	private := setupPython{exe: "private/python.exe"}
	calls := 0
	chosen, err := selectSetupPython([]setupPython{private, {exe: "missing-global"}}, func(candidate setupPython) ([]byte, error) {
		calls++
		if candidate.exe == private.exe {
			return []byte(`{"major":3,"minor":12,"bits":64}`), nil
		}
		return nil, errors.New("missing")
	})
	if err != nil || chosen.exe != private.exe || calls != 1 {
		t.Fatalf("private interpreter not reused: %v %v %d", chosen, err, calls)
	}
}
func TestSetupSkipsBrokenAnd32BitPython(t *testing.T) {
	candidates := []setupPython{{exe: "broken"}, {exe: "32bit"}, {exe: "64bit", prefix: []string{"-3.12"}}}
	chosen, err := selectSetupPython(candidates, func(candidate setupPython) ([]byte, error) {
		switch candidate.exe {
		case "broken":
			return nil, errors.New("missing base interpreter")
		case "32bit":
			return []byte(`{"major":3,"minor":12,"bits":32}`), nil
		default:
			return []byte(`{"major":3,"minor":12,"bits":64}`), nil
		}
	})
	if err != nil || chosen.exe != "64bit" {
		t.Fatalf("compatible fallback not chosen: %v %v", chosen, err)
	}
	args := chosen.arguments("-m", "venv", ".venv")
	if strings.Join(args, " ") != "-3.12 -m venv .venv" {
		t.Fatal("launcher selection was lost", args)
	}
	_, err = selectSetupPython(candidates[:1], func(setupPython) ([]byte, error) { return nil, errors.New("missing") })
	if err == nil || !strings.Contains(err.Error(), "64-bit") {
		t.Fatal("missing interpreter lacks actionable error", err)
	}
}
func TestSetupDiagnosticsRetainPackageFailureWithoutCredentials(t *testing.T) {
	diagnostics := setupDiagnostics("Installing required video packages", errors.New("exit status 1"), []byte("ERROR: No matching distribution found for deno\nhttps://name:password@example.com/private?token=secret\nBearer private-token sk-private-key"))
	if !strings.Contains(diagnostics, "No matching distribution found for deno") {
		t.Fatal("package failure discarded")
	}
	for _, secret := range []string{"password", "private-token", "sk-private-key", "token=secret"} {
		if strings.Contains(diagnostics, secret) {
			t.Fatalf("secret in setup details: %s", secret)
		}
	}
	output := &setupOutput{}
	output.Write([]byte(strings.Repeat("a", 20000)))
	output.Write([]byte("FINAL ERROR"))
	if len(output.data) > 16000 || !strings.HasSuffix(string(output.data), "FINAL ERROR") {
		t.Fatal("setup output is unbounded or lost error tail")
	}
}

func TestPrivatePythonIgnoresIncompleteRepair(t *testing.T) {
	dir := t.TempDir()
	makeEnv := func(name string, ready bool) {
		t.Helper()
		base := filepath.Join(dir, name)
		if err := os.MkdirAll(filepath.Join(base, "Scripts"), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(base, "Scripts", "python.exe"), []byte("test"), 0600); err != nil {
			t.Fatal(err)
		}
		if ready {
			if err := os.WriteFile(filepath.Join(base, ".vyra-ready"), []byte("verified"), 0600); err != nil {
				t.Fatal(err)
			}
		}
	}
	makeEnv(".venv", false)
	makeEnv(".venv-repair-300", false)
	if got := privateClipsPython(dir); got != filepath.Join(dir, ".venv", "Scripts", "python.exe") {
		t.Fatal(got)
	}
	makeEnv(".venv-repair-100", true)
	makeEnv(".venv-repair-200", true)
	if got := privateClipsPython(dir); got != filepath.Join(dir, ".venv-repair-200", "Scripts", "python.exe") {
		t.Fatal(got)
	}
	if _, err := os.Stat(filepath.Join(dir, ".venv", "Scripts", "python.exe")); err != nil {
		t.Fatal("old environment changed", err)
	}
}
