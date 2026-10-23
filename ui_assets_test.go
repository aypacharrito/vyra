package main

import (
	"bytes"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"
)

func TestEveryEntryAssetIsServed(t *testing.T) {
	a := &app{csrf: "asset-test"}
	handler := a.routes()
	index := httptest.NewRecorder()
	handler.ServeHTTP(index, httptest.NewRequest("GET", "http://127.0.0.1:48791/", nil))
	if index.Code != 200 {
		t.Fatalf("index returned %d", index.Code)
	}
	references := regexp.MustCompile(`(?:href|src)="(/[^"?#]+)"`).FindAllStringSubmatch(index.Body.String(), -1)
	if len(references) == 0 {
		t.Fatal("entry document has no assets")
	}
	for _, match := range references {
		path := match[1]
		t.Run(path, func(t *testing.T) {
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, httptest.NewRequest("GET", "http://127.0.0.1:48791"+path, nil))
			expected, err := content.ReadFile("web" + path)
			if err != nil {
				t.Fatal(err)
			}
			if response.Code != 200 || !bytes.Equal(response.Body.Bytes(), expected) {
				t.Fatalf("referenced asset %s returned %d or different content", path, response.Code)
			}
			if strings.HasSuffix(path, ".css") && !strings.HasPrefix(response.Header().Get("Content-Type"), "text/css") {
				t.Fatalf("stylesheet returned wrong MIME: %s", response.Header().Get("Content-Type"))
			}
		})
	}
}
