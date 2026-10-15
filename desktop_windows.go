//go:build windows

package main

import (
	"fmt"
	"path/filepath"
	"runtime"
	"sync/atomic"
	"syscall"
	"unsafe"

	"github.com/jchv/go-webview2/pkg/edge"
)

// VYRA owns this Windows window. WebView2 is an embedded rendering runtime;
// no browser executable, browser profile, or --app shortcut is launched.
var desktopUser32 = syscall.NewLazyDLL("user32.dll")
var desktopHWND atomic.Uintptr
var desktopBrowser *edge.Chromium // accessed only on the UI thread
var desktopReady bool

const desktopClass = "VYRA.Desktop.Window"

type nativePoint struct{ X, Y int32 }
type nativeMessage struct {
	HWND           uintptr
	Message        uint32
	WParam, LParam uintptr
	Time           uint32
	Point          nativePoint
	Private        uint32
}
type nativeWindowClass struct {
	Size, Style                        uint32
	Proc                               uintptr
	ClassExtra, WindowExtra            int32
	Instance, Icon, Cursor, Background uintptr
	Menu, Name                         *uint16
	SmallIcon                          uintptr
}
type nativeMinMax struct{ Reserved, MaxSize, MaxPosition, MinTrackSize, MaxTrackSize nativePoint }

func nativeText(s string) *uint16 { p, _ := syscall.UTF16PtrFromString(s); return p }
func desktopMessage(hwnd uintptr, msg uint32, wp, lp uintptr) uintptr {
	switch msg {
	case 0x0113: // WM_TIMER: diagnostic capture after the first page has painted.
		desktopUser32.NewProc("KillTimer").Call(hwnd, 1)
		captureDesktopPreview(pendingDesktopPreview)
		return 0
	case 0x0005, 0x0003: // WM_SIZE / WM_MOVE
		if desktopReady {
			desktopBrowser.Resize()
			_ = desktopBrowser.NotifyParentWindowPositionChanged()
		}
		return 0
	case 0x0007:
		if desktopReady {
			desktopBrowser.Focus()
		}
		return 0
	case 0x0010:
		desktopUser32.NewProc("DestroyWindow").Call(hwnd)
		return 0
	case 0x0002:
		desktopReady = false
		desktopHWND.Store(0)
		desktopUser32.NewProc("PostQuitMessage").Call(0)
		return 0
	}
	result, _, _ := desktopUser32.NewProc("DefWindowProcW").Call(hwnd, uintptr(msg), wp, lp)
	return result
}
func openDesktop(url string) error {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	desktopUser32.NewProc("SetProcessDPIAware").Call()
	instance, _, _ := kernel32.NewProc("GetModuleHandleW").Call(0)
	icon, _, _ := desktopUser32.NewProc("LoadImageW").Call(instance, uintptr(unsafe.Pointer(nativeText("APP"))), 1, 0, 0, 0x8040)
	cursor, _, _ := desktopUser32.NewProc("LoadCursorW").Call(0, 32512)
	brush, _, _ := syscall.NewLazyDLL("gdi32.dll").NewProc("CreateSolidBrush").Call(0x00110b08)
	defer syscall.NewLazyDLL("gdi32.dll").NewProc("DeleteObject").Call(brush)
	wc := nativeWindowClass{Proc: syscall.NewCallback(desktopMessage), Instance: instance, Icon: icon, SmallIcon: icon, Cursor: cursor, Background: brush, Name: nativeText(desktopClass)}
	wc.Size = uint32(unsafe.Sizeof(wc))
	registered, _, registerErr := desktopUser32.NewProc("RegisterClassExW").Call(uintptr(unsafe.Pointer(&wc)))
	if registered == 0 {
		return fmt.Errorf("Could not register VYRA window: %v", registerErr)
	}
	defer desktopUser32.NewProc("UnregisterClassW").Call(uintptr(unsafe.Pointer(wc.Name)), instance)
	hwnd, _, windowErr := desktopUser32.NewProc("CreateWindowExW").Call(0, uintptr(unsafe.Pointer(wc.Name)), uintptr(unsafe.Pointer(nativeText("VYRA — Your intelligence, your control"))), 0x00cf0000, 0x80000000, 0x80000000, 1500, 940, 0, 0, instance, 0)
	if hwnd == 0 {
		return fmt.Errorf("Could not create VYRA window: %v", windowErr)
	}
	desktopHWND.Store(hwnd)
	defer desktopUser32.NewProc("DestroyWindow").Call(hwnd)
	dark := int32(1)
	syscall.NewLazyDLL("dwmapi.dll").NewProc("DwmSetWindowAttribute").Call(hwnd, 20, uintptr(unsafe.Pointer(&dark)), 4)
	desktopUser32.NewProc("SendMessageW").Call(hwnd, 0x0080, 0, icon)
	desktopUser32.NewProc("SendMessageW").Call(hwnd, 0x0080, 1, icon)
	syscall.NewLazyDLL("shell32.dll").NewProc("SetCurrentProcessExplicitAppUserModelID").Call(uintptr(unsafe.Pointer(nativeText("VYRA.Desktop"))))
	desktopBrowser = edge.NewChromium()
	desktopBrowser.DataPath = filepath.Join(userDataDir(), "WebView2")
	desktopBrowser.SetPermission(edge.CoreWebView2PermissionKindCamera, edge.CoreWebView2PermissionStateDeny)
	desktopBrowser.SetPermission(edge.CoreWebView2PermissionKindGeolocation, edge.CoreWebView2PermissionStateDeny)
	if !desktopBrowser.Embed(hwnd) {
		desktopUser32.NewProc("MessageBoxW").Call(hwnd, uintptr(unsafe.Pointer(nativeText("VYRA needs the Microsoft WebView2 Runtime. Install the Evergreen Runtime from Microsoft, then reopen VYRA."))), uintptr(unsafe.Pointer(nativeText("VYRA needs a Windows component"))), 0x10)
		return fmt.Errorf("WebView2 could not start")
	}
	settings, err := desktopBrowser.GetSettings()
	if err != nil {
		return err
	}
	_ = settings.PutAreDevToolsEnabled(false)
	_ = settings.PutIsStatusBarEnabled(false)
	_ = settings.PutAreHostObjectsAllowed(false)
	desktopBrowser.Init("window.VYRA_NATIVE=true;")
	desktopBrowser.NavigationCompletedCallback = func(sender *edge.ICoreWebView2, args *edge.ICoreWebView2NavigationCompletedEventArgs) {
		queueDesktopPreview(sender)
	}
	desktopReady = true
	desktopBrowser.Resize()
	_ = desktopBrowser.Show()
	desktopBrowser.Navigate(url)
	desktopUser32.NewProc("ShowWindow").Call(hwnd, 1)
	// Installers launch with STARTUPINFO/SW_HIDE to suppress console helpers.
	// A second call applies VYRA's own visibility after that startup override.
	desktopUser32.NewProc("ShowWindow").Call(hwnd, 5)
	desktopUser32.NewProc("UpdateWindow").Call(hwnd)
	var msg nativeMessage
	for {
		result, _, _ := desktopUser32.NewProc("GetMessageW").Call(uintptr(unsafe.Pointer(&msg)), 0, 0, 0)
		if int32(result) <= 0 {
			break
		}
		desktopUser32.NewProc("TranslateMessage").Call(uintptr(unsafe.Pointer(&msg)))
		desktopUser32.NewProc("DispatchMessageW").Call(uintptr(unsafe.Pointer(&msg)))
	}
	runtime.KeepAlive(desktopBrowser)
	desktopBrowser = nil
	return nil
}
func desktopStatus() map[string]any {
	hwnd := desktopHWND.Load()
	visible := uintptr(0)
	if hwnd != 0 {
		visible, _, _ = desktopUser32.NewProc("IsWindowVisible").Call(hwnd)
	}
	return map[string]any{"engine": "WebView2", "nativeWindow": hwnd != 0, "visible": visible != 0}
}
func closeDesktop() {
	if hwnd := desktopHWND.Load(); hwnd != 0 {
		desktopUser32.NewProc("PostMessageW").Call(hwnd, 0x0010, 0, 0)
	}
}
func showExisting() {
	hwnd, _, _ := desktopUser32.NewProc("FindWindowW").Call(uintptr(unsafe.Pointer(nativeText(desktopClass))), 0)
	if hwnd != 0 {
		desktopUser32.NewProc("ShowWindow").Call(hwnd, 9)
		desktopUser32.NewProc("SetForegroundWindow").Call(hwnd)
	}
}
