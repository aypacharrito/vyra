package main

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestStatusAndLocalSecurity(t *testing.T) {
	a := newApp()
	a.apiKey = ""
	h := a.routes()
	r := httptest.NewRequest("GET", "http://127.0.0.1:48791/api/status", nil)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != 200 {
		t.Fatal(w.Code)
	}
	var data map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &data); err != nil {
		t.Fatal(err)
	}
	if data["local"] != true {
		t.Fatal(data)
	}
	r2 := httptest.NewRequest("POST", "http://127.0.0.1:48791/api/chat", strings.NewReader(`{"messages":[{"role":"user","content":"hello"}]}`))
	w2 := httptest.NewRecorder()
	h.ServeHTTP(w2, r2)
	if w2.Code != 403 {
		t.Fatalf("expected 403 missing CSRF, got %d", w2.Code)
	}
	r3 := httptest.NewRequest("GET", "http://evil.example/api/status", nil)
	w3 := httptest.NewRecorder()
	h.ServeHTTP(w3, r3)
	if w3.Code != 403 {
		t.Fatalf("expected 403 hostile host, got %d", w3.Code)
	}
}
func TestKeyValidation(t *testing.T) {
	a := newApp()
	a.apiKey = ""
	h := a.routes()
	r := httptest.NewRequest("POST", "http://127.0.0.1:48791/api/settings", strings.NewReader(`{"key":"invalid","persist":false}`))
	r.Header.Set("X-VYRA-SESSION", a.csrf)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != 400 {
		t.Fatalf("expected 400, got %d", w.Code)
	}
	if a.apiKey != "" {
		t.Fatal("Invalid key unexpectedly saved")
	}
}
