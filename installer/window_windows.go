//go:build windows

package main

import (
	"fmt"
	"path/filepath"
	"runtime"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

var user32 = syscall.NewLazyDLL("user32.dll")
var gdi32 = syscall.NewLazyDLL("gdi32.dll")
var setupKernel = syscall.NewLazyDLL("kernel32.dll")
var defWindowProc = user32.NewProc("DefWindowProcW")
var createWindow = user32.NewProc("CreateWindowExW")
var sendMessage = user32.NewProc("SendMessageW")
var invalidate = user32.NewProc("InvalidateRect")

type rect struct{ left, top, right, bottom int32 }
type point struct{ x, y int32 }
type windowClass struct {
	size, style                        uint32
	proc                               uintptr
	classExtra, windowExtra            int32
	instance, icon, cursor, background uintptr
	menu, name                         *uint16
	smallIcon                          uintptr
}
type message struct {
	hwnd           uintptr
	message        uint32
	wparam, lparam uintptr
	time           uint32
	pt             point
	private        uint32
}
type paintStruct struct {
	dc              uintptr
	erase           int32
	area            rect
	restore, update int32
	reserved        [32]byte
}
type drawItem struct {
	controlType, controlID, itemID, action, state uint32
	hwnd, dc                                      uintptr
	area                                          rect
	data                                          uintptr
}
type setupWindow struct {
	hwnd, primary, secondary, instance, icon uintptr
	fonts                                    [4]uintptr
	scale                                    float64
	auto, preview                            bool
	mu                                       sync.Mutex
	phase                                    string
	progress                                 int
	status, failure                          string
	exitCode                                 int
}

var setupUI *setupWindow

func utf16(s string) *uint16     { p, _ := syscall.UTF16PtrFromString(s); return p }
func color(r, g, b byte) uintptr { return uintptr(r) | uintptr(g)<<8 | uintptr(b)<<16 }

var background = color(12, 18, 28)
var panel = color(22, 33, 48)
var accent = color(164, 207, 245)
var foreground = color(235, 242, 251)
var muted = color(151, 170, 194)

func (u *setupWindow) px(v int32) int32 { return int32(float64(v)*u.scale + .5) }
func (u *setupWindow) box(x, y, w, h int32) rect {
	return rect{u.px(x), u.px(y), u.px(x + w), u.px(y + h)}
}
func fill(dc uintptr, r rect, ink uintptr) {
	brush, _, _ := gdi32.NewProc("CreateSolidBrush").Call(ink)
	user32.NewProc("FillRect").Call(dc, uintptr(unsafe.Pointer(&r)), brush)
	gdi32.NewProc("DeleteObject").Call(brush)
}
func (u *setupWindow) text(dc uintptr, value string, font int, ink uintptr, r rect, flags uintptr) {
	old, _, _ := gdi32.NewProc("SelectObject").Call(dc, u.fonts[font])
	gdi32.NewProc("SetBkMode").Call(dc, 1)
	gdi32.NewProc("SetTextColor").Call(dc, ink)
	user32.NewProc("DrawTextW").Call(dc, uintptr(unsafe.Pointer(utf16(value))), ^uintptr(0), uintptr(unsafe.Pointer(&r)), flags|0x800) // DT_NOPREFIX
	gdi32.NewProc("SelectObject").Call(dc, old)
}
func (u *setupWindow) paint(dc uintptr) {
	u.mu.Lock()
	phase, progress, status, failure := u.phase, u.progress, u.status, u.failure
	u.mu.Unlock()
	fill(dc, u.box(0, 0, 680, 492), background)
	fill(dc, u.box(0, 0, 680, 4), accent)
	user32.NewProc("DrawIconEx").Call(dc, uintptr(u.px(36)), uintptr(u.px(37)), u.icon, uintptr(u.px(72)), uintptr(u.px(72)), 0, 0, 3)
	u.text(dc, "VYRA", 2, foreground, u.box(126, 40, 360, 40), 0)
	u.text(dc, "PERSONAL INTELLIGENCE  /  "+version, 0, muted, u.box(128, 82, 460, 24), 0)
	title := "Your next idea starts here."
	detail := "A focused workspace for AI, projects and your creative work."
	if phase == "working" {
		title = "Making room for what’s next."
		detail = "Setting up VYRA. This window will show you each step."
	}
	if phase == "done" {
		title = "Welcome to VYRA."
		detail = "Your workspace is ready. Open it and start building."
	}
	if phase == "error" {
		title = "One more step to finish."
		detail = "Setup needs your attention. Close VYRA, then try again."
	}
	u.text(dc, title, 2, foreground, u.box(36, 137, 608, 46), 0)
	u.text(dc, detail, 1, muted, u.box(36, 190, 608, 30), 0)
	fill(dc, u.box(36, 236, 608, 82), panel)
	u.text(dc, "YOUR WINDOWS ACCOUNT", 0, accent, u.box(54, 249, 560, 20), 0)
	u.text(dc, appDir(), 1, foreground, u.box(54, 275, 565, 26), 0x4000|0x20) // path ellipsis
	line := "Desktop + Start Menu shortcuts · VYRA Clips included"
	if u.preview {
		line = "SETUP PREVIEW · No files or settings will be changed"
	}
	if phase == "error" {
		line = failure
	}
	u.text(dc, line, 0, muted, u.box(36, 332, 608, 40), 0x10) // word wrap
	fill(dc, u.box(36, 380, 608, 4), panel)
	if progress > 0 {
		fill(dc, u.box(36, 380, int32(progress)*608/100, 4), accent)
	}
	u.text(dc, status, 0, muted, u.box(36, 399, 334, 48), 0x10)
	u.text(dc, "Your saved key, conversations and projects stay in your profile.", 0, muted, u.box(36, 459, 608, 21), 0)
}
func (u *setupWindow) drawButton(item *drawItem) {
	ink, label, textInk := panel, "Cancel", foreground
	if item.controlID == 101 {
		ink, textInk = accent, background
		u.mu.Lock()
		phase := u.phase
		u.mu.Unlock()
		label = map[string]string{"ready": "Install VYRA", "working": "Installing…", "done": "Open VYRA", "error": "Try again"}[phase]
		if u.preview && phase == "done" {
			label = "Close preview"
		}
	} else {
		u.mu.Lock()
		phase := u.phase
		u.mu.Unlock()
		if phase == "done" || phase == "error" {
			label = "Close"
		}
	}
	if item.state&4 != 0 {
		ink = color(48, 63, 82)
		textInk = muted
	}
	if item.state&1 != 0 {
		ink = color(126, 161, 205)
	}
	fill(item.dc, item.area, ink)
	u.text(item.dc, label, 3, textInk, item.area, 0x1|0x4|0x20)
	if item.state&0x10 != 0 {
		r := item.area
		r.left += 4
		r.top += 4
		r.right -= 4
		r.bottom -= 4
		user32.NewProc("DrawFocusRect").Call(item.dc, uintptr(unsafe.Pointer(&r)))
	}
}
func (u *setupWindow) repaint() {
	invalidate.Call(u.hwnd, 0, 0)
	invalidate.Call(u.primary, 0, 0)
	invalidate.Call(u.secondary, 0, 0)
}
func (u *setupWindow) report(progress int, status string) {
	u.mu.Lock()
	u.progress = progress
	u.status = status
	u.mu.Unlock()
	user32.NewProc("PostMessageW").Call(u.hwnd, 0x8001, 0, 0)
}
func (u *setupWindow) begin() {
	u.mu.Lock()
	if u.phase == "working" {
		u.mu.Unlock()
		return
	}
	u.phase, u.failure = "working", ""
	u.mu.Unlock()
	user32.NewProc("EnableWindow").Call(u.primary, 0)
	user32.NewProc("EnableWindow").Call(u.secondary, 0)
	u.repaint()
	go func() {
		if u.auto {
			time.Sleep(1700 * time.Millisecond)
		}
		var err error
		if u.preview {
			for i := 10; i <= 100; i += 15 {
				u.report(i, "Previewing setup progress…")
				time.Sleep(180 * time.Millisecond)
			}
		} else {
			err = install(u.report)
		}
		u.mu.Lock()
		if err != nil {
			u.phase, u.failure, u.status, u.exitCode = "error", err.Error(), "Setup could not finish.", 1
		} else {
			u.phase, u.progress, u.status, u.exitCode = "done", 100, "Installed successfully.", 0
		}
		u.mu.Unlock()
		user32.NewProc("PostMessageW").Call(u.hwnd, 0x8002, 0, 0)
	}()
}
func (u *setupWindow) openApp() {
	if !u.preview {
		if err := hiddenCommand(filepath.Join(appDir(), "VYRA.exe")).Start(); err != nil {
			dialog("Open VYRA", "VYRA is installed. Open it from the Desktop or Start Menu shortcut.", 0x30)
		}
	}
	user32.NewProc("DestroyWindow").Call(u.hwnd)
}

// The lparam is supplied by Windows for the duration of this callback.
// A pointer parameter keeps that native pointer intact across the Go boundary.
func setupProc(hwnd uintptr, msg uint32, wp uintptr, lp unsafe.Pointer) uintptr {
	u := setupUI
	switch msg {
	case 0x0f: // WM_PAINT
		var p paintStruct
		dc, _, _ := user32.NewProc("BeginPaint").Call(hwnd, uintptr(unsafe.Pointer(&p)))
		u.paint(dc)
		user32.NewProc("EndPaint").Call(hwnd, uintptr(unsafe.Pointer(&p)))
		return 0
	case 0x2b: // WM_DRAWITEM
		u.drawButton((*drawItem)(lp))
		return 1
	case 0x111: // WM_COMMAND
		u.mu.Lock()
		phase := u.phase
		u.mu.Unlock()
		if wp&0xffff == 101 {
			if phase == "done" {
				u.openApp()
			} else {
				u.begin()
			}
		}
		if wp&0xffff == 102 && phase != "working" {
			user32.NewProc("DestroyWindow").Call(hwnd)
		}
		return 0
	case 0x10: // WM_CLOSE -- never interrupt file replacement
		u.mu.Lock()
		busy := u.phase == "working"
		u.mu.Unlock()
		if !busy {
			user32.NewProc("DestroyWindow").Call(hwnd)
		}
		return 0
	case 0x113:
		user32.NewProc("KillTimer").Call(hwnd, wp)
		if wp == 1 {
			u.begin()
		} else if wp == 2 {
			u.openApp()
		}
		return 0
	case 0x8001:
		u.repaint()
		return 0
	case 0x8002:
		user32.NewProc("EnableWindow").Call(u.primary, 1)
		user32.NewProc("EnableWindow").Call(u.secondary, 1)
		// Update accessible button names along with their drawn labels.
		u.mu.Lock()
		phase := u.phase
		u.mu.Unlock()
		label := "Try again"
		if phase == "done" {
			label = "Open VYRA"
			if u.preview {
				label = "Close preview"
			}
		}
		user32.NewProc("SetWindowTextW").Call(u.primary, uintptr(unsafe.Pointer(utf16(label))))
		user32.NewProc("SetWindowTextW").Call(u.secondary, uintptr(unsafe.Pointer(utf16("Close"))))
		u.repaint()
		if u.auto && phase == "done" {
			user32.NewProc("SetTimer").Call(hwnd, 2, 1100, 0)
		}
		return 0
	case 2:
		user32.NewProc("PostQuitMessage").Call(uintptr(u.exitCode))
		return 0
	}
	result, _, _ := defWindowProc.Call(hwnd, uintptr(msg), wp, uintptr(lp))
	return result
}

func runSetup(auto, preview bool) error {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	instance, _, _ := setupKernel.NewProc("GetModuleHandleW").Call(0)
	dc, _, _ := user32.NewProc("GetDC").Call(0)
	dpi, _, _ := gdi32.NewProc("GetDeviceCaps").Call(dc, 88)
	user32.NewProc("ReleaseDC").Call(0, dc)
	u := &setupWindow{instance: instance, auto: auto, preview: preview, scale: float64(dpi) / 96, phase: "ready", status: "Ready when you are."}
	if u.scale < 1 {
		u.scale = 1
	}
	setupUI = u
	iconName := utf16("APP")
	u.icon, _, _ = user32.NewProc("LoadImageW").Call(instance, uintptr(unsafe.Pointer(iconName)), 1, uintptr(u.px(128)), uintptr(u.px(128)), 0)
	if u.icon == 0 {
		return fmt.Errorf("VYRA setup icon is missing from this build")
	}
	defer user32.NewProc("DestroyIcon").Call(u.icon)
	cursor, _, _ := user32.NewProc("LoadCursorW").Call(0, 32512)
	name := utf16("VYRA.Setup.Window")
	class := windowClass{size: uint32(unsafe.Sizeof(windowClass{})), proc: syscall.NewCallback(setupProc), instance: instance, icon: u.icon, smallIcon: u.icon, cursor: cursor, name: name}
	if n, _, err := user32.NewProc("RegisterClassExW").Call(uintptr(unsafe.Pointer(&class))); n == 0 {
		return fmt.Errorf("could not create setup window: %v", err)
	}
	defer user32.NewProc("UnregisterClassW").Call(uintptr(unsafe.Pointer(name)), instance)
	for i, spec := range [][2]int32{{12, 400}, {15, 400}, {30, 600}, {14, 600}} {
		u.fonts[i], _, _ = gdi32.NewProc("CreateFontW").Call(uintptr(-u.px(spec[0])), 0, 0, 0, uintptr(spec[1]), 0, 0, 0, 1, 0, 0, 5, 0, uintptr(unsafe.Pointer(utf16("Segoe UI"))))
		defer gdi32.NewProc("DeleteObject").Call(u.fonts[i])
	}
	const style = 0x00c00000 | 0x00080000 | 0x00020000 | 0x02000000 // caption, system menu, minimize, clip children
	r := u.box(0, 0, 680, 492)
	user32.NewProc("AdjustWindowRectEx").Call(uintptr(unsafe.Pointer(&r)), style, 0, 0)
	w, h := r.right-r.left, r.bottom-r.top
	sw, _, _ := user32.NewProc("GetSystemMetrics").Call(0)
	sh, _, _ := user32.NewProc("GetSystemMetrics").Call(1)
	u.hwnd, _, _ = createWindow.Call(0, uintptr(unsafe.Pointer(name)), uintptr(unsafe.Pointer(utf16("VYRA Setup"))), style, uintptr((int32(sw)-w)/2), uintptr((int32(sh)-h)/2), uintptr(w), uintptr(h), 0, 0, instance, 0)
	if u.hwnd == 0 {
		return fmt.Errorf("could not open VYRA setup")
	}
	dark := int32(1)
	syscall.NewLazyDLL("dwmapi.dll").NewProc("DwmSetWindowAttribute").Call(u.hwnd, 20, uintptr(unsafe.Pointer(&dark)), 4)
	for _, id := range []uintptr{101, 102} {
		x, width, label := int32(482), int32(162), "Install VYRA"
		if id == 102 {
			x, width, label = 370, 96, "Cancel"
		}
		handle, _, _ := createWindow.Call(0, uintptr(unsafe.Pointer(utf16("BUTTON"))), uintptr(unsafe.Pointer(utf16(label))), 0x5001000b, uintptr(u.px(x)), uintptr(u.px(404)), uintptr(u.px(width)), uintptr(u.px(42)), u.hwnd, id, instance, 0)
		if handle == 0 {
			user32.NewProc("DestroyWindow").Call(u.hwnd)
			return fmt.Errorf("could not create setup controls")
		}
		sendMessage.Call(handle, 0x30, u.fonts[3], 1)
		if id == 101 {
			u.primary = handle
		} else {
			u.secondary = handle
		}
	}
	user32.NewProc("ShowWindow").Call(u.hwnd, 5)
	user32.NewProc("UpdateWindow").Call(u.hwnd)
	user32.NewProc("SetFocus").Call(u.primary)
	if auto {
		user32.NewProc("SetTimer").Call(u.hwnd, 1, 100, 0)
	}
	var m message
	for {
		n, _, _ := user32.NewProc("GetMessageW").Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if int32(n) <= 0 {
			break
		}
		// Standard keyboard navigation and activation for accessible native buttons.
		if handled, _, _ := user32.NewProc("IsDialogMessageW").Call(u.hwnd, uintptr(unsafe.Pointer(&m))); handled == 0 {
			user32.NewProc("TranslateMessage").Call(uintptr(unsafe.Pointer(&m)))
			user32.NewProc("DispatchMessageW").Call(uintptr(unsafe.Pointer(&m)))
		}
	}
	return nil
}
