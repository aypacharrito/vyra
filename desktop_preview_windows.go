//go:build windows

package main

import (
	"os"
	"syscall"
	"unsafe"

	"github.com/jchv/go-webview2/pkg/edge"
)

// Optional app-owned render diagnostic. CapturePreview records this embedded
// view directly through WebView2, without driving other windows or browsers.
type previewHandler struct {
	VTable *[4]uintptr
	Stream unsafe.Pointer
	Path   string
}

var desktopPreview *previewHandler
var pendingDesktopPreview *edge.ICoreWebView2

func queueDesktopPreview(view *edge.ICoreWebView2) {
	if os.Getenv("VYRA_CAPTURE_PATH") == "" || desktopPreview != nil {
		return
	}
	pendingDesktopPreview = view
	desktopUser32.NewProc("SetTimer").Call(desktopHWND.Load(), 1, 2500, 0)
}

func comMethod(object unsafe.Pointer, index int, args ...uintptr) uintptr {
	table := *(*unsafe.Pointer)(object)
	proc := *(*uintptr)(unsafe.Add(table, uintptr(index)*unsafe.Sizeof(uintptr(0))))
	result, _, _ := syscall.SyscallN(proc, append([]uintptr{uintptr(object)}, args...)...)
	return result
}
func captureDesktopPreview(view *edge.ICoreWebView2) {
	path := os.Getenv("VYRA_CAPTURE_PATH")
	if path == "" || desktopPreview != nil {
		return
	}
	h := &previewHandler{Path: path}
	h.VTable = &[4]uintptr{
		syscall.NewCallback(func(self *previewHandler, iid unsafe.Pointer, out *unsafe.Pointer) uintptr {
			*out = unsafe.Pointer(self)
			return 0
		}),
		syscall.NewCallback(func(self *previewHandler) uintptr { return 1 }),
		syscall.NewCallback(func(self *previewHandler) uintptr { return 1 }),
		syscall.NewCallback(func(callback *previewHandler, status uintptr) uintptr {
			comMethod(callback.Stream, 2)
			if int32(status) < 0 {
				_ = os.WriteFile(callback.Path+".error", []byte("WebView2 capture failed"), 0600)
			}
			return 0
		}),
	}
	result, _, _ := syscall.NewLazyDLL("shlwapi.dll").NewProc("SHCreateStreamOnFileEx").Call(uintptr(unsafe.Pointer(nativeText(path))), 0x1011, 0x80, 1, 0, uintptr(unsafe.Pointer(&h.Stream)))
	if int32(result) < 0 {
		return
	}
	desktopPreview = h
	// ICoreWebView2::CapturePreview (slot 30), PNG format 0.
	status := comMethod(unsafe.Pointer(view), 30, 0, uintptr(h.Stream), uintptr(unsafe.Pointer(h)))
	if int32(status) < 0 {
		comMethod(h.Stream, 2)
		_ = os.WriteFile(path+".error", []byte("WebView2 capture could not start"), 0600)
	}
}
