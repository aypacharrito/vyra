package main

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"testing"
)

func TestResearchToolsAndHistory(t *testing.T) {
	for _, enabled := range []bool{true, false} {
		a := testApp(t)
		a.prefs.WebSearch = &enabled
		a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
			var body struct {
				Tools []map[string]string `json:"tools"`
				Input []message           `json:"input"`
				Max   int                 `json:"max_output_tokens"`
			}
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Fatal(err)
			}
			if enabled && (len(body.Tools) != 1 || body.Tools[0]["type"] != "web_search") {
				t.Fatal("Missing live search")
			}
			if !enabled && len(body.Tools) != 0 {
				t.Fatal("Search preference ignored")
			}
			if len(body.Input) != 60 || body.Input[0].Content != "earliest context" || body.Max < 16000 {
				t.Fatal("Conversation silently shortened")
			}
			return fakeResponse(200, `{"status":"completed","output":[{"content":[{"type":"output_text","text":"Done"}]}]}`), nil
		})
		msgs := make([]message, 60)
		for i := range msgs {
			msgs[i] = message{Role: "user", Content: "More context"}
		}
		msgs[0].Content = "earliest context"
		result, err := a.complete(context.Background(), chatInput{Messages: msgs})
		if err != nil || result != "Done" {
			t.Fatal(result, err)
		}
	}
}
func TestUnicodeCitationsOrderedAndSafe(t *testing.T) {
	var response responseEnvelope
	raw := `{"output":[{"content":[{"type":"output_text","text":"🌍 First citeA, second citeB","annotations":[{"type":"url_citation","start_index":8,"end_index":13,"url":"https://example.com/a","title":"First"},{"type":"url_citation","start_index":22,"end_index":27,"url":"https://example.com/b","title":"Second"},{"type":"url_citation","start_index":0,"end_index":1,"url":"javascript:alert(1)"}]}]}]}`
	if err := json.Unmarshal([]byte(raw), &response); err != nil {
		t.Fatal(err)
	}
	text, sources := responseContent(response)
	if len(sources) != 2 || sources[0].Title != "First" || !strings.Contains(text, "🌍 First [1](https://example.com/a)") || !strings.Contains(text, "[2](https://example.com/b)") {
		t.Fatal(text, sources)
	}
}
func TestStreamFinalAnswerIncludesCitations(t *testing.T) {
	a := testApp(t)
	a.client.Transport = roundTripFunc(func(*http.Request) (*http.Response, error) {
		return fakeResponse(200, "data: {\"type\":\"response.web_search_call.searching\"}\n\ndata: {\"type\":\"response.completed\",\"response\":{\"output\":[{\"content\":[{\"type\":\"output_text\",\"text\":\"Result cite\",\"annotations\":[{\"type\":\"url_citation\",\"start_index\":7,\"end_index\":11,\"url\":\"https://example.com\",\"title\":\"Evidence\"}]}]}]}}\n\n"), nil
	})
	w := api(t, a, "POST", "/api/chat/stream", `{"messages":[{"role":"user","content":"Find evidence"}]}`)
	for _, expected := range []string{`"type":"status"`, `"type":"answer"`, `Sources:`, `Evidence`, `"type":"done"`} {
		if !strings.Contains(w.Body.String(), expected) {
			t.Fatal(w.Body.String())
		}
	}
}
func TestExternalLinksCannotOpenCommandsOrLocalServices(t *testing.T) {
	for _, input := range []string{"file:///C:/Windows/system32/cmd.exe", "javascript:alert(1)", "https://user:password@example.com", "http://127.0.0.1:8765/", "http://localhost/", "http://192.168.1.1/", "https://example.com\ncommand"} {
		if _, err := externalURL(input); err == nil {
			t.Fatalf("Accepted %q", input)
		}
	}
	if _, err := externalURL("https://accounts.google.com/o/oauth2/v2/auth?client_id=public"); err != nil {
		t.Fatal(err)
	}
	a := testApp(t)
	r, _ := http.NewRequest("POST", "http://127.0.0.1:48791/api/open-external", strings.NewReader(`{"url":"https://example.com"}`))
	w := api(t, a, "POST", "/api/open-external", `{"url":"file:///C:/bad"}`)
	if w.Code != 400 {
		t.Fatal(w.Code)
	}
	_ = r
}
