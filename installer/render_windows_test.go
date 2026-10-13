//go:build windows

package main

import (
	"image"
	"image/png"
	"os"
	"runtime"
	"testing"
	"unsafe"
)

// Render the real native drawing into an offscreen bitmap for release QA.
// No installed files, shortcuts, credentials or user windows are touched.
func TestNativeSetupResourcesAndRender(t *testing.T) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	instance, _, _ := setupKernel.NewProc("GetModuleHandleW").Call(0)
	u := &setupWindow{instance: instance, scale: 1, preview: true, phase: "ready", status: "Ready when you are."}
	u.icon, _, _ = user32.NewProc("LoadImageW").Call(instance, uintptr(unsafe.Pointer(utf16("APP"))), 1, 128, 128, 0)
	if u.icon == 0 {
		t.Fatal("native VYRA icon missing")
	}
	defer user32.NewProc("DestroyIcon").Call(u.icon)
	for i, spec := range [][2]int32{{12, 400}, {15, 400}, {30, 600}, {14, 600}} {
		u.fonts[i], _, _ = gdi32.NewProc("CreateFontW").Call(uintptr(-spec[0]), 0, 0, 0, uintptr(spec[1]), 0, 0, 0, 1, 0, 0, 5, 0, uintptr(unsafe.Pointer(utf16("Segoe UI"))))
		if u.fonts[i] == 0 {
			t.Fatal("setup font could not be created")
		}
		defer gdi32.NewProc("DeleteObject").Call(u.fonts[i])
	}
	dc, _, _ := gdi32.NewProc("CreateCompatibleDC").Call(0)
	if dc == 0 {
		t.Fatal("offscreen setup drawing unavailable")
	}
	defer gdi32.NewProc("DeleteDC").Call(dc)
	// BITMAPINFOHEADER with a top-down, 32-bit DIB.
	info := struct {
		size                   uint32
		width, height          int32
		planes, bits           uint16
		compression, imageSize uint32
		xppm, yppm             int32
		used, important        uint32
	}{size: 40, width: 680, height: -492, planes: 1, bits: 32}
	var pixels unsafe.Pointer
	bitmap, _, _ := gdi32.NewProc("CreateDIBSection").Call(dc, uintptr(unsafe.Pointer(&info)), 0, uintptr(unsafe.Pointer(&pixels)), 0, 0)
	if bitmap == 0 || pixels == nil {
		t.Fatal("setup bitmap could not be created")
	}
	defer gdi32.NewProc("DeleteObject").Call(bitmap)
	old, _, _ := gdi32.NewProc("SelectObject").Call(dc, bitmap)
	defer gdi32.NewProc("SelectObject").Call(dc, old)
	u.paint(dc)
	u.drawButton(&drawItem{controlID: 101, dc: dc, area: u.box(482, 404, 162, 42)})
	u.drawButton(&drawItem{controlID: 102, dc: dc, area: u.box(370, 404, 96, 42)})
	gdi32.NewProc("GdiFlush").Call()
	data := unsafe.Slice((*byte)(pixels), 680*492*4)
	if data[0] != 245 || data[1] != 207 || data[2] != 164 {
		t.Fatal("setup did not render its accent bar")
	}
	if output := os.Getenv("VYRA_SETUP_RENDER"); output != "" {
		img := image.NewRGBA(image.Rect(0, 0, 680, 492))
		for i := 0; i < len(data); i += 4 {
			img.Pix[i], img.Pix[i+1], img.Pix[i+2], img.Pix[i+3] = data[i+2], data[i+1], data[i], 255
		}
		f, err := os.Create(output)
		if err != nil {
			t.Fatal(err)
		}
		if err := png.Encode(f, img); err != nil {
			f.Close()
			t.Fatal(err)
		}
		if err := f.Close(); err != nil {
			t.Fatal(err)
		}
	}
}
