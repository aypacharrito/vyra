//go:build windows

package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
	"unsafe"
)

type blob struct {
	size uint32
	data *byte
}

var crypt32 = syscall.NewLazyDLL("crypt32.dll")
var protect = crypt32.NewProc("CryptProtectData")
var unprotect = crypt32.NewProc("CryptUnprotectData")
var kernel32 = syscall.NewLazyDLL("kernel32.dll")
var localFree = kernel32.NewProc("LocalFree")

func blobFor(bytes []byte) blob {
	if len(bytes) == 0 {
		return blob{}
	}
	return blob{uint32(len(bytes)), &bytes[0]}
}
func windowsCrypt(input []byte, encrypt bool) ([]byte, error) {
	b := blobFor(input)
	var out blob
	flags := uintptr(1) // CRYPTPROTECT_UI_FORBIDDEN
	var ret uintptr
	var callErr error
	if encrypt {
		ret, _, callErr = protect.Call(uintptr(unsafe.Pointer(&b)), 0, 0, 0, 0, flags, uintptr(unsafe.Pointer(&out)))
	} else {
		ret, _, callErr = unprotect.Call(uintptr(unsafe.Pointer(&b)), 0, 0, 0, 0, flags, uintptr(unsafe.Pointer(&out)))
	}
	if ret == 0 {
		return nil, fmt.Errorf("Windows credential encryption failed: %v", callErr)
	}
	defer localFree.Call(uintptr(unsafe.Pointer(out.data)))
	result := make([]byte, int(out.size))
	copy(result, unsafe.Slice(out.data, int(out.size)))
	return result, nil
}
func keyFile() string {
	path := os.Getenv("APPDATA")
	if path == "" {
		path = os.TempDir()
	}
	return filepath.Join(path, "VYRA", "api-key.dpapi")
}
func saveKey(key string) error {
	v, e := windowsCrypt([]byte(key), true)
	if e != nil {
		return e
	}
	p := keyFile()
	if err := os.MkdirAll(filepath.Dir(p), 0700); err != nil {
		return err
	}
	return os.WriteFile(p, v, 0600)
}
func loadKey() (string, error) {
	v, e := os.ReadFile(keyFile())
	if e != nil {
		return "", e
	}
	raw, e := windowsCrypt(v, false)
	return string(raw), e
}
func deleteKey() error { return os.Remove(keyFile()) }
func hideWorker(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
}
func edgePath() string {
	for _, root := range []string{os.Getenv("PROGRAMFILES(X86)"), os.Getenv("PROGRAMFILES"), os.Getenv("LOCALAPPDATA")} {
		if root == "" {
			continue
		}
		for _, p := range []string{"Microsoft\\Edge\\Application\\msedge.exe", "Microsoft\\Edge Beta\\Application\\msedge.exe"} {
			f := filepath.Join(root, p)
			if _, e := os.Stat(f); e == nil {
				return f
			}
		}
	}
	return ""
}
func openDesktop(url string) {
	time.Sleep(300 * time.Millisecond)
	if edge := edgePath(); edge != "" {
		c := exec.Command(edge, "--app="+url, "--window-size=1500,940", "--new-window")
		hideWorker(c)
		if c.Start() == nil {
			return
		}
	}
	c := exec.Command("rundll32.exe", "url.dll,FileProtocolHandler", url)
	hideWorker(c)
	_ = c.Start()
}
func showExisting() { openDesktop("http://127.0.0.1:48791/") }

var _ = errors.New
