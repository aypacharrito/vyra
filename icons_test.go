package main

import (
	"net/http/httptest"
	"testing"
)

func TestDesktopIconsAreServed(t *testing.T) {
	a := testApp(t)
	for _, icon := range []struct{ path, mime, magic string }{
		{"/favicon.ico", "image/x-icon", "\x00\x00\x01\x00"},
		{"/icon.png", "image/png", "\x89PNG"},
		{"/icon.svg", "image/svg+xml", "<svg"},
	} {
		w := httptest.NewRecorder()
		a.routes().ServeHTTP(w, httptest.NewRequest("GET", "http://127.0.0.1:48791"+icon.path, nil))
		if w.Code != 200 || w.Header().Get("Content-Type") != icon.mime || len(w.Body.Bytes()) < 4 || string(w.Body.Bytes()[:4]) != icon.magic {
			t.Fatalf("%s: missing or invalid desktop icon", icon.path)
		}
	}
}
