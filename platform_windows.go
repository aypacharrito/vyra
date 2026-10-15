//go:build windows

package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
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
func keyFile() string { return filepath.Join(userDataDir(), "api-key.dpapi") }
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
func openExternal(url string) error {
	verb, _ := syscall.UTF16PtrFromString("open")
	target, err := syscall.UTF16PtrFromString(url)
	if err != nil {
		return err
	}
	result, _, _ := syscall.NewLazyDLL("shell32.dll").NewProc("ShellExecuteW").Call(0, uintptr(unsafe.Pointer(verb)), uintptr(unsafe.Pointer(target)), 0, 0, 1)
	if result <= 32 {
		return fmt.Errorf("Windows could not open the web link (%d)", result)
	}
	return nil
}

var _ = errors.New
