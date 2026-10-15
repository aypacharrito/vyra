package main

import (
	"net/http/httptest"
	"testing"
)

func TestVersionComparisons(t *testing.T) {
	cases := []struct {
		a, b string
		want bool
	}{
		{"1.1.1", "1.1.0", true},
		{"1.2.0", "1.1.9", true},
		{"2.0.0", "1.99.99", true},
		{"1.1.0", "1.1.0", false},
		{"1.0.0", "1.1.0", false},
		{"garbage", "1.0.0", false},
	}
	for _, tc := range cases {
		if got := newerVersion(tc.a, tc.b); got != tc.want {
			t.Fatalf("%s %s: %v", tc.a, tc.b, got)
		}
	}
}
func TestManifestSafety(t *testing.T) {
	m := updateManifest{Version: "1.2.0", URL: "https://vyra-five-lac.vercel.app/downloads/VYRA-Setup.exe", SHA256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
	if !validManifest(m) {
		t.Fatal("valid manifest rejected")
	}
	m.URL = "https://untrusted.example/downloads/VYRA-Setup.exe"
	if validManifest(m) {
		t.Fatal("host not enforced")
	}
}

func TestOpenAITestRequiresSavedKey(t *testing.T) {
	a := testApp(t)
	a.apiKey = ""
	h := a.routes()
	request := httptest.NewRequest("POST", "http://127.0.0.1:48791/api/openai/test", nil)
	request.Header.Set("X-VYRA-SESSION", a.csrf)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, request)
	if w.Code != 400 {
		t.Fatalf("expected missing key 400, got %d", w.Code)
	}
}
