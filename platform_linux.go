//go:build !windows

package main

import (
	"fmt"
	"os"
	"os/exec"
)

func saveKey(key string) error {
	return fmt.Errorf("encrypted key storage is only available in Windows desktop build")
}
func loadKey() (string, error) { return "", fmt.Errorf("not saved") }
func deleteKey() error         { return nil }
func hideWorker(cmd *exec.Cmd) {}
func openDesktop(url string) error {
	fmt.Println("VYRA running at", url)
	if os.Getenv("VYRA_BROWSER") != "" {
		exec.Command("xdg-open", url).Start()
	}
	return nil
}
func showExisting() { _ = openDesktop("http://127.0.0.1:48791/") }
func closeDesktop() {}
func desktopStatus() map[string]any {
	return map[string]any{"engine": "headless", "nativeWindow": false, "visible": false}
}
func openExternal(url string) error { return exec.Command("xdg-open", url).Start() }

func desktopWindowAction(action string) bool { return false }
