//go:build windows

package main

import (
	"context"
	"errors"
	"os/exec"
	"time"
)

// Older releases left their Python worker running after closing the desktop.
// Verify its VYRA status, exact launch arguments and Windows session before
// replacing it, and leave a publishing worker alone until submission finishes.
func stopLegacyWorker() error {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", legacyWorkerStopScript())
	hideWorker(cmd)
	if err := cmd.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) && exitErr.ExitCode() == 42 {
			return errors.New("A post is still uploading. Wait for it to finish, then try opening Clips again.")
		}
		return errors.New("The previous Clips session could not restart. Exit VYRA and reopen it. If this continues, close the older VYRA Clips/Python window, then try again.")
	}
	return nil
}
