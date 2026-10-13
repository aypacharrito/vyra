//go:build windows

// VYRA per-user setup. No admin access, no background service, and no bundled secrets.
package main

import (
	"archive/zip"
	"bytes"
	"embed"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

//go:embed payload.zip
var bundled embed.FS

var version = "1.2.0"

var msgbox = syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW")

func dialog(title, body string, flags uintptr) int {
	t, _ := syscall.UTF16PtrFromString(title)
	b, _ := syscall.UTF16PtrFromString(body)
	n, _, _ := msgbox.Call(0, uintptr(unsafe.Pointer(b)), uintptr(unsafe.Pointer(t)), flags)
	return int(n)
}
func appDir() string {
	root := os.Getenv("LOCALAPPDATA")
	if root == "" {
		root = os.TempDir()
	}
	return filepath.Join(root, "Programs", "VYRA")
}
func payload() ([]byte, error) { return bundled.ReadFile("payload.zip") }
func extract(dst string) error {
	raw, err := payload()
	if err != nil {
		return err
	}
	zr, err := zip.NewReader(bytes.NewReader(raw), int64(len(raw)))
	if err != nil {
		return err
	}
	for _, f := range zr.File {
		normalized := filepath.Clean(filepath.FromSlash(f.Name))
		if filepath.IsAbs(normalized) || normalized == ".." || strings.HasPrefix(normalized, ".."+string(os.PathSeparator)) {
			return errors.New("invalid installer payload")
		}
		target := filepath.Join(dst, normalized)
		if f.FileInfo().IsDir() {
			if err := os.MkdirAll(target, 0755); err != nil {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
			return err
		}
		reader, err := f.Open()
		if err != nil {
			return err
		}
		temp := target + ".new"
		w, err := os.OpenFile(temp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0644)
		if err != nil {
			reader.Close()
			return err
		}
		_, cpErr := io.Copy(w, reader)
		reader.Close()
		closeErr := w.Close()
		if cpErr != nil {
			return cpErr
		}
		if closeErr != nil {
			return closeErr
		}
		var replaced bool
		for i := 0; i < 35; i++ { // Allow VYRA time to exit when initiated by its updater.
			if e := os.Rename(temp, target); e == nil {
				replaced = true
				break
			}
			// On Windows, replacing the destination can fail if the old EXE is still running.
			if e := os.Remove(target); e == nil {
				if e = os.Rename(temp, target); e == nil {
					replaced = true
					break
				}
			}
			time.Sleep(500 * time.Millisecond)
		}
		if !replaced {
			return fmt.Errorf("could not replace %s; close VYRA and retry", filepath.Base(target))
		}
	}
	return nil
}
func shortcut(psPath, lnkPath, target, desc string) error {
	// Write a tiny local PowerShell script using environment variables instead of embedding untrusted quoting.
	script := `$ErrorActionPreference='Stop'
$w=New-Object -ComObject WScript.Shell
$dest=$env:VYRA_SHORTCUT
if($env:VYRA_IS_DESKTOP -eq 'true'){$dest=Join-Path $w.SpecialFolders('Desktop') 'VYRA.lnk'}
New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
$s=$w.CreateShortcut($dest)
$s.TargetPath=$env:VYRA_TARGET
$s.WorkingDirectory=Split-Path $env:VYRA_TARGET
$s.Description=$env:VYRA_DESC
if($env:VYRA_ARGS){$s.Arguments=$env:VYRA_ARGS}
$s.IconLocation=$env:VYRA_TARGET + ',0'
$s.Save()
`
	if err := os.WriteFile(psPath, []byte(script), 0600); err != nil {
		return err
	}
	defer os.Remove(psPath)
	cmd := exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", psPath)
	cmd.Env = append(os.Environ(), "VYRA_SHORTCUT="+lnkPath, "VYRA_TARGET="+target, "VYRA_DESC="+desc, "VYRA_IS_DESKTOP="+fmt.Sprint(strings.HasSuffix(lnkPath, "Desktop\\VYRA.lnk") || strings.HasSuffix(lnkPath, "Desktop/VYRA.lnk")), "VYRA_ARGS="+map[bool]string{true: "--uninstall", false: ""}[strings.Contains(lnkPath, "Uninstall VYRA.lnk")])
	return cmd.Run()
}
func paths() (string, string) {
	home, _ := os.UserHomeDir()
	start := filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "VYRA")
	return filepath.Join(home, "Desktop", "VYRA.lnk"), start
}
func install() error {
	dst := appDir()
	if err := os.MkdirAll(dst, 0755); err != nil {
		return err
	}
	if err := extract(dst); err != nil {
		return err
	}
	self, err := os.Executable()
	if err != nil {
		return err
	}
	uninstall := filepath.Join(dst, "Uninstall-VYRA.exe")
	if b, err := os.ReadFile(self); err == nil {
		if err := os.WriteFile(uninstall, b, 0700); err != nil {
			return err
		}
	}
	desktop, start := paths()
	if err := shortcut(filepath.Join(os.TempDir(), "vyra-shortcut.ps1"), desktop, filepath.Join(dst, "VYRA.exe"), "VYRA Intelligence"); err != nil {
		return err
	}
	if err := shortcut(filepath.Join(os.TempDir(), "vyra-shortcut.ps1"), filepath.Join(start, "VYRA.lnk"), filepath.Join(dst, "VYRA.exe"), "VYRA Intelligence"); err != nil {
		return err
	}
	if err := shortcut(filepath.Join(os.TempDir(), "vyra-shortcut.ps1"), filepath.Join(start, "Uninstall VYRA.lnk"), uninstall, "Remove VYRA"); err != nil {
		return err
	}
	// Visible under Windows Settings > Apps > Installed Apps, no admin permission.
	arp := `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\VYRA`
	for _, kv := range [][2]string{{"DisplayName", "VYRA"}, {"DisplayVersion", version}, {"Publisher", "VYRA Open Beta"}, {"InstallLocation", dst}, {"DisplayIcon", filepath.Join(dst, "VYRA.exe")}, {"UninstallString", `"` + uninstall + `" --uninstall`}} {
		_ = exec.Command("reg.exe", "add", arp, "/v", kv[0], "/t", "REG_SZ", "/d", kv[1], "/f").Run()
	}
	return nil
}
func uninstall() error {
	desktop, start := paths()
	_ = exec.Command("reg.exe", "delete", `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\VYRA`, "/f").Run()
	_ = exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", `$p=(New-Object -ComObject WScript.Shell).SpecialFolders('Desktop');Remove-Item -LiteralPath (Join-Path $p 'VYRA.lnk') -ErrorAction SilentlyContinue`).Run()
	_ = os.Remove(desktop)
	_ = os.RemoveAll(start)
	dir := appDir()
	// The installer can't remove its own running executable. Clean it up just after exit.
	script := filepath.Join(os.TempDir(), "vyra-cleanup.ps1")
	content := `Start-Sleep -Seconds 3
for($n=0;$n -lt 15;$n++){try{Remove-Item -LiteralPath $env:VYRA_REMOVE -Force -Recurse -ErrorAction Stop; break}catch{Start-Sleep -Seconds 1}}
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
`
	if err := os.WriteFile(script, []byte(content), 0600); err != nil {
		return err
	}
	c := exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File", script)
	c.Env = append(os.Environ(), "VYRA_REMOVE="+dir)
	return c.Start()
}
func main() {
	auto := len(os.Args) > 1 && os.Args[1] == "--auto-update"
	remove := len(os.Args) > 1 && os.Args[1] == "--uninstall"
	if remove {
		if dialog("Remove VYRA?", "Uninstall VYRA from this Windows account? Your saved OpenAI key and conversations will stay under your user profile.", 0x24) != 6 {
			return
		}
		if err := uninstall(); err != nil {
			dialog("VYRA Uninstall", err.Error(), 0x10)
		} else {
			dialog("VYRA", "VYRA has been scheduled for removal. Your personal data is preserved.", 0x40)
		}
		return
	}
	if !auto && dialog("Install VYRA", "Install or update VYRA in your Windows user account? This creates Desktop and Start Menu shortcuts and includes VYRA Clips files.", 0x24) != 6 {
		return
	}
	if auto {
		time.Sleep(1700 * time.Millisecond)
	}
	if err := install(); err != nil {
		dialog("VYRA Setup Failed", err.Error(), 0x10)
		os.Exit(1)
	}
	dialog("VYRA Installed", "VYRA is installed! You can open it from your Desktop or Start Menu. Connect OpenAI in Settings using your own API key.", 0x40)
	app := filepath.Join(appDir(), "VYRA.exe")
	if err := exec.Command(app).Start(); err != nil {
		dialog("VYRA", "Installation succeeded, but VYRA couldn't start automatically. Open it from your Desktop.", 0x30)
	}
}
