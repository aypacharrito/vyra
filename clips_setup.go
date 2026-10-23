package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const clipsProbeCode = "from zoneinfo import ZoneInfo; ZoneInfo('America/Los_Angeles'); import fastapi, uvicorn, multipart, openai, boto3, requests, cryptography, dotenv, yt_dlp, deno, yt_dlp_ejs; deno.find_deno_bin()"
const pythonIdentityCode = "import sys, struct, json; print(json.dumps({'major':sys.version_info.major,'minor':sys.version_info.minor,'bits':struct.calcsize('P')*8}))"

type clipsSetupStatus struct {
	State       string `json:"state"`
	Detail      string `json:"detail"`
	Diagnostics string `json:"diagnostics,omitempty"`
}

var videoSetup struct {
	sync.Mutex
	status clipsSetupStatus
}

func setupSnapshot() clipsSetupStatus {
	videoSetup.Lock()
	defer videoSetup.Unlock()
	return videoSetup.status
}
func setupReport(state, detail string) {
	videoSetup.Lock()
	videoSetup.status = clipsSetupStatus{State: state, Detail: detail}
	videoSetup.Unlock()
}

// Bound package-manager output and redact credentials before displaying errors.
type setupOutput struct{ data []byte }

func (output *setupOutput) Write(data []byte) (int, error) {
	output.data = append(output.data, data...)
	if len(output.data) > 16000 {
		output.data = output.data[len(output.data)-16000:]
	}
	return len(data), nil
}

var setupSecret = regexp.MustCompile(`(?i)sk-[a-z0-9_-]+|bearer\s+[^\s]+|https?://[^\s]+`)

func setupDiagnostics(stage string, err error, output []byte) string {
	text := strings.TrimSpace(string(output))
	if text == "" {
		text = err.Error()
	}
	text = setupSecret.ReplaceAllString(text, "[redacted]")
	return stage + "\n" + text
}
func setupFailure(stage string, err error, output []byte) {
	videoSetup.Lock()
	videoSetup.status = clipsSetupStatus{State: "failed", Detail: stage + " failed. Open Setup details below for the exact error, then choose Repair video tools.", Diagnostics: setupDiagnostics(stage, err, output)}
	videoSetup.Unlock()
}

type setupPython struct {
	exe    string
	prefix []string
}

func (python setupPython) arguments(args ...string) []string {
	return append(append([]string{}, python.prefix...), args...)
}
func compatibleSetupPython(output []byte) bool {
	var identity struct{ Major, Minor, Bits int }
	return json.Unmarshal([]byte(strings.TrimSpace(string(output))), &identity) == nil && identity.Major == 3 && identity.Minor >= 11 && identity.Minor <= 13 && identity.Bits == 64
}
func selectSetupPython(candidates []setupPython, probe func(setupPython) ([]byte, error)) (setupPython, error) {
	for _, candidate := range candidates {
		output, err := probe(candidate)
		if err == nil && compatibleSetupPython(output) {
			return candidate, nil
		}
	}
	return setupPython{}, errors.New("VYRA needs 64-bit Python 3.11, 3.12 or 3.13. Install 64-bit Python 3.12 from python.org, then choose Repair video tools. A 32-bit, missing or unsupported interpreter cannot install these video packages.")
}

// A completed generation is immutable: repairs never overwrite loaded DLLs.
func privateClipsPython(dir string) string {
	entries, _ := os.ReadDir(dir)
	names := []string{}
	for _, entry := range entries {
		if entry.IsDir() && strings.HasPrefix(entry.Name(), ".venv-repair-") {
			base := filepath.Join(dir, entry.Name())
			if _, err := os.Stat(filepath.Join(base, ".vyra-ready")); err == nil {
				if _, err = os.Stat(filepath.Join(base, "Scripts", "python.exe")); err == nil {
					names = append(names, entry.Name())
				}
			}
		}
	}
	sort.Sort(sort.Reverse(sort.StringSlice(names)))
	name := ".venv"
	if len(names) > 0 {
		name = names[0]
	}
	return filepath.Join(dir, name, "Scripts", "python.exe")
}

func setupPythonCandidates(dir string) []setupPython {
	candidates := []setupPython{{exe: privateClipsPython(dir)}}
	if py, err := exec.LookPath("py"); err == nil {
		for _, v := range []string{"-3.12-64", "-3.11-64", "-3.13-64", "-3.12", "-3.11", "-3.13"} {
			candidates = append(candidates, setupPython{exe: py, prefix: []string{v}})
		}
	}
	if python, err := exec.LookPath("python"); err == nil {
		candidates = append(candidates, setupPython{exe: python})
	}
	return candidates
}
func runSetupCommand(ctx context.Context, dir string, python setupPython, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, python.exe, python.arguments(args...)...)
	cmd.Dir = dir
	hideWorker(cmd)
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PIP_DISABLE_PIP_VERSION_CHECK=1")
	output := &setupOutput{}
	cmd.Stdout = output
	cmd.Stderr = output
	err := cmd.Run()
	return output.data, err
}
func openClipsSetup() error {
	videoSetup.Lock()
	if videoSetup.status.State == "running" {
		videoSetup.Unlock()
		return errors.New("Video tools are already installing. Progress appears in VYRA Clips.")
	}
	videoSetup.status = clipsSetupStatus{State: "running", Detail: "Checking your video workspace…"}
	videoSetup.Unlock()
	go func() {
		dir := workerDirectory()
		if _, err := os.Stat(filepath.Join(dir, "requirements.txt")); err != nil {
			setupReport("failed", "Video tools are missing. Install the complete VYRA package, then try again.")
			return
		}
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
		defer cancel()
		python, err := selectSetupPython(setupPythonCandidates(dir), func(candidate setupPython) ([]byte, error) {
			check, done := context.WithTimeout(ctx, 8*time.Second)
			defer done()
			return runSetupCommand(check, dir, candidate, "-c", pythonIdentityCode)
		})
		if err != nil {
			setupFailure("Finding compatible Python", err, nil)
			return
		}
		if err = ensureMediaTools(ctx, func(detail string) { setupReport("running", detail) }); err != nil {
			setupFailure("Preparing the video engine", err, nil)
			return
		}
		venv := privateClipsPython(dir)
		if python.exe == venv {
			if _, probeErr := runSetupCommand(ctx, dir, python, "-c", clipsProbeCode); probeErr == nil {
				setupReport("ready", "Video tools verified. Opening your studio…")
				return
			}
		}

		// Create beside the old environment, without renaming/deleting files that
		// Windows, another worker or a security scanner may still have open.
		environment := filepath.Join(dir, ".venv-repair-"+strconv.FormatInt(time.Now().UnixNano(), 10))
		setupReport("running", "Creating a fresh private video workspace…")
		output, createErr := runSetupCommand(ctx, dir, python, "-m", "venv", environment)
		if createErr != nil {
			setupFailure("Creating the Python workspace", createErr, output)
			return
		}
		venv = filepath.Join(environment, "Scripts", "python.exe")

		private := setupPython{exe: venv}
		steps := []struct {
			detail string
			args   []string
		}{
			{"Repairing the private package installer", []string{"-m", "ensurepip", "--upgrade"}},
			{"Updating the private package installer", []string{"-m", "pip", "install", "--upgrade", "--timeout", "30", "--retries", "2", "pip"}},
			{"Installing required video packages", []string{"-m", "pip", "install", "--only-binary=:all:", "--timeout", "30", "--retries", "2", "-r", "requirements.txt"}},
			{"Checking installed video packages", []string{"-c", clipsProbeCode}},
		}
		for _, step := range steps {
			setupReport("running", step.detail+"…")
			output, stepErr := runSetupCommand(ctx, dir, private, step.args...)
			if stepErr != nil {
				setupFailure(step.detail, stepErr, output)
				return
			}
		}
		if err := os.WriteFile(filepath.Join(environment, ".vyra-ready"), []byte("verified\n"), 0600); err != nil {
			setupFailure("Activating the verified video workspace", err, nil)
			return
		}
		setupReport("ready", "Video tools verified. Opening your studio…")
	}()
	return nil
}

var _ io.Writer = (*setupOutput)(nil)
