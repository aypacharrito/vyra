package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func testApp(t *testing.T) *app {
	t.Helper()
	t.Setenv("VYRA_DATA_DIR", t.TempDir())
	t.Setenv("OPENAI_API_KEY", "")
	a := newApp()
	a.apiKey = "sk-test-placeholder-not-a-real-key"
	return a
}
func api(t *testing.T, a *app, method, path, body string) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest(method, "http://127.0.0.1:48791"+path, strings.NewReader(body))
	r.Header.Set("X-VYRA-SESSION", a.csrf)
	w := httptest.NewRecorder()
	a.routes().ServeHTTP(w, r)
	return w
}
func fakeResponse(code int, body string) *http.Response {
	return &http.Response{StatusCode: code, Body: io.NopCloser(strings.NewReader(body)), Header: make(http.Header)}
}

func TestStreamIncludesProjectContextAndHandlesEvents(t *testing.T) {
	a := testApp(t)
	a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.String() != "https://api.openai.com/v1/responses" {
			t.Fatal(r.URL)
		}
		var b map[string]any
		json.NewDecoder(r.Body).Decode(&b)
		if b["stream"] != true || b["store"] != false {
			t.Fatal(b)
		}
		raw, _ := json.Marshal(b)
		if !strings.Contains(string(raw), "Project reference material") || !strings.Contains(string(raw), "example.go") {
			t.Fatal("Project material missing")
		}
		return fakeResponse(200, "data: {\"type\":\"response.created\"}\r\n\r\ndata: {\"type\":\"response.output_text.delta\",\"delta\":\"Hello \"}\r\n\r\ndata: {\"type\":\"response.output_text.delta\",\"delta\":\"world 🌍\"}\n\ndata: {\"type\":\"response.completed\"}\n\n"), nil
	})
	w := api(t, a, "POST", "/api/chat/stream", `{"messages":[{"role":"user","content":"Study this code"}],"mode":"code","context":"example.go"}`)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"type":"done"`) || !strings.Contains(w.Body.String(), "world 🌍") {
		t.Fatal(w.Code, w.Body.String())
	}
}
func TestIncompleteStreamIsNotSuccess(t *testing.T) {
	for _, ending := range []string{`{"type":"response.incomplete"}`, `{"type":"error","message":"private secret provider message"}`, ""} {
		a := testApp(t)
		a.client.Transport = roundTripFunc(func(*http.Request) (*http.Response, error) {
			return fakeResponse(200, "data: {\"type\":\"response.output_text.delta\",\"delta\":\"partial\"}\n\ndata: "+ending+"\n\n"), nil
		})
		w := api(t, a, "POST", "/api/chat/stream", `{"messages":[{"role":"user","content":"hello"}]}`)
		if !strings.Contains(w.Body.String(), `"type":"error"`) || strings.Contains(w.Body.String(), `"type":"done"`) || strings.Contains(w.Body.String(), "private secret") {
			t.Fatal(w.Body.String())
		}
	}
}
func TestProviderErrorsNeverEchoSecrets(t *testing.T) {
	a := testApp(t)
	a.client.Transport = roundTripFunc(func(*http.Request) (*http.Response, error) {
		return fakeResponse(429, `{"error":{"message":"sk-test-placeholder-not-a-real-key"}}`), nil
	})
	w := api(t, a, "POST", "/api/chat", `{"messages":[{"role":"user","content":"hi"}]}`)
	if w.Code != 502 || strings.Contains(w.Body.String(), a.apiKey) || !strings.Contains(w.Body.String(), "billing") {
		t.Fatal(w.Body.String())
	}
}
func TestConnectionValidationDoesNotPartiallyReplaceKey(t *testing.T) {
	a := testApp(t)
	old := a.apiKey
	w := api(t, a, "POST", "/api/settings", `{"key":"sk-new-placeholder-not-a-real-key","model":"../../evil","persist":false}`)
	if w.Code != 400 || a.apiKey != old {
		t.Fatal("Settings mutation occurred before validation", w.Code)
	}
}
func TestSavedPreferencesAndWorkspaceSurviveRestart(t *testing.T) {
	a := testApp(t)
	w := api(t, a, "PUT", "/api/preferences", `{"model":"gpt-6-astra","instructions":"Be concise","speakReplies":true,"language":"es-US"}`)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	w = api(t, a, "PUT", "/api/workspace", `{"chats":[],"projects":[{"id":"p","name":"VYRA","note":"Study code"}],"active":"","projectId":"p","mode":"code"}`)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	b := newApp()
	if b.model != "gpt-6-astra" || !b.prefs.SpeakReplies {
		t.Fatal("Preferences lost")
	}
	w = api(t, b, "GET", "/api/workspace", "")
	if !strings.Contains(w.Body.String(), `"projectId": "p"`) {
		t.Fatal(w.Body.String())
	}
}
func TestTaskClaimsPauseAfterFailureAndRespectBudget(t *testing.T) {
	a := testApp(t)
	calls := atomic.Int32{}
	a.client.Transport = roundTripFunc(func(*http.Request) (*http.Response, error) { calls.Add(1); return fakeResponse(429, `{}`), nil })
	a.tasks.Tasks = []task{{ID: "one", Name: "Review", Prompt: "review code", Model: a.model, Mode: "code", Schedule: "interval", IntervalMinutes: 60, Enabled: true, MaxRuns: 2, NextRun: time.Now().Add(-time.Hour)}}
	_, err := a.beginTask("one", true)
	if err != nil {
		t.Fatal(err)
	}
	a.tasks.wg.Wait()
	if calls.Load() != 1 || a.tasks.Tasks[0].Enabled || a.tasks.Runs[0].Status != "failed" || a.tasks.Tasks[0].RunCount != 1 {
		t.Fatal(a.tasks.snapshot())
	}
	if _, err = a.beginTask("one", true); err == nil {
		t.Fatal("Failed schedule was retried")
	}
	a.client.Transport = roundTripFunc(func(*http.Request) (*http.Response, error) {
		return fakeResponse(200, `{"status":"completed","output":[{"content":[{"type":"output_text","text":"review result"}]}]}`), nil
	})
	_, err = a.beginTask("one", false)
	if err != nil {
		t.Fatal(err)
	}
	a.tasks.wg.Wait()
	if _, err = a.beginTask("one", false); err == nil {
		t.Fatal("Run budget exceeded")
	}
	b := openTaskStore(a.tasks.path)
	if len(b.Runs) != 2 || b.Runs[0].Result != "review result" {
		t.Fatal("Run history not saved", b.snapshot())
	}
}
func TestTaskCrashRecoveryNeverRetriesAnUncertainCall(t *testing.T) {
	path := filepath.Join(t.TempDir(), "tasks.json")
	if err := atomicJSON(path, map[string]any{"tasks": []task{{ID: "x", Enabled: true}}, "runs": []taskRun{{ID: "r", TaskID: "x", Status: "running"}}}); err != nil {
		t.Fatal(err)
	}
	s := openTaskStore(path)
	if s.Tasks[0].Enabled || s.Runs[0].Status != "interrupted" {
		t.Fatal(s.snapshot())
	}
	raw, err := os.ReadFile(path)
	if err != nil || !strings.Contains(string(raw), "interrupted") {
		t.Fatal(err)
	}
}
func TestTaskCancellationAndSingleConcurrency(t *testing.T) {
	a := testApp(t)
	started := make(chan struct{})
	a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		close(started)
		<-r.Context().Done()
		return nil, r.Context().Err()
	})
	a.tasks.Tasks = []task{{ID: "x", Name: "task", Prompt: "task", Mode: "assistant", Model: a.model, MaxRuns: 3}}
	if _, err := a.beginTask("x", false); err != nil {
		t.Fatal(err)
	}
	<-started
	if _, err := a.beginTask("x", false); err == nil {
		t.Fatal("Concurrent task permitted")
	}
	w := api(t, a, "POST", "/api/tasks/x/cancel", `{}`)
	if w.Code != 200 {
		t.Fatal(w.Code)
	}
	a.tasks.wg.Wait()
	if a.tasks.Runs[0].Status != "cancelled" {
		t.Fatal(a.tasks.snapshot())
	}
}
func TestCorruptTaskStoragePreserved(t *testing.T) {
	path := filepath.Join(t.TempDir(), "tasks.json")
	os.WriteFile(path, []byte("corrupt data"), 0600)
	s := openTaskStore(path)
	if s.loadError == "" {
		t.Fatal("Corruption went unreported")
	}
	if s.saveLocked() == nil {
		t.Fatal("Corrupt data was overwritten")
	}
	raw, _ := os.ReadFile(path)
	if string(raw) != "corrupt data" {
		t.Fatal(string(raw))
	}
}
func TestLongConversationAndModelValidation(t *testing.T) {
	messages := make([]message, 100)
	for i := range messages {
		messages[i] = message{Role: "user", Content: "hello"}
	}
	if err := validateChat(chatInput{Messages: messages}); err != nil {
		t.Fatal(err)
	}
	for _, model := range []string{"../../path", "gpt-live-transcribe", "gpt-4o-mini-tts", "gpt-image-1", ""} {
		if validTextModel(model) {
			t.Fatal(model)
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	a := testApp(t)
	a.aiSlots <- struct{}{}
	a.aiSlots <- struct{}{}
	if a.acquireAI(ctx) == nil {
		t.Fatal("Cancelled wait acquired a slot")
	}
}
