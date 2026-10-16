package main

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"time"
)

type clipsSetupStatus struct {
	State  string `json:"state"`
	Detail string `json:"detail"`
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
	videoSetup.status = clipsSetupStatus{state, detail}
	videoSetup.Unlock()
}
func openClipsSetup() error {
	videoSetup.Lock()
	if videoSetup.status.State == "running" {
		videoSetup.Unlock()
		return errors.New("Video tools are already installing. Progress appears in VYRA Clips.")
	}
	videoSetup.status = clipsSetupStatus{"running", "Preparing your video tools…"}
	videoSetup.Unlock()
	go func() {
		dir := workerDirectory()
		if _, err := os.Stat(filepath.Join(dir, "requirements.txt")); err != nil {
			setupReport("failed", "Video tools are missing. Install the complete VYRA package, then try again.")
			return
		}
		python, err := exec.LookPath("python")
		if err != nil {
			python, err = exec.LookPath("py")
		}
		if err != nil {
			setupReport("failed", "Install Python 3.11 or newer, then choose Set up video tools again.")
			return
		}
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
		defer cancel()
		if err = ensureMediaTools(ctx, func(detail string) { setupReport("running", detail) }); err != nil {
			setupReport("failed", err.Error())
			return
		}
		run := func(exe string, args ...string) error {
			cmd := exec.CommandContext(ctx, exe, args...)
			cmd.Dir = dir
			hideWorker(cmd)
			return cmd.Run()
		}
		venv := filepath.Join(dir, ".venv", "Scripts", "python.exe")
		if _, err := os.Stat(venv); err != nil {
			setupReport("running", "Creating your private video workspace…")
			if err = run(python, "-m", "venv", ".venv"); err != nil {
				setupReport("failed", "Python could not prepare the video workspace. Check your Python installation and try again.")
				return
			}
		}
		setupReport("running", "Installing video tools. This can take a few minutes…")
		if err = run(venv, "-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt"); err != nil {
			setupReport("failed", "Video tools could not finish installing. Check your internet connection and Python installation, then try again.")
			return
		}
		setupReport("ready", "Video tools installed. Opening your studio…")
	}()
	return nil
}
