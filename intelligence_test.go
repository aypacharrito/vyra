package main

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"testing"
)

func TestIntelligenceExecutesProjectAndPreservesReasoning(t *testing.T) {
	a := testApp(t)
	w := api(t, a, "PUT", "/api/workspace", `{"chats":[{"id":"old","title":"Keep my chat","messages":[]}],"projects":[],"active":"old","projectId":"","mode":"assistant"}`)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	calls := 0
	a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		var body map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if calls == 1 {
			return fakeResponse(200, `{"status":"completed","output":[{"type":"reasoning","id":"r1","encrypted_content":"opaque-test","summary":[]},{"type":"function_call","name":"vyra_save_project","call_id":"save1","arguments":"{\"id\":\"\",\"name\":\"Content strategy\",\"note\":\"Compare measured retention\"}"}]}`), nil
		}
		if !strings.Contains(string(body["input"]), "opaque-test") || !strings.Contains(string(body["input"]), "function_call_output") || !strings.Contains(string(body["input"]), "Content strategy") {
			t.Fatal("Tool result or reasoning lost", string(body["input"]))
		}
		return fakeResponse(200, `{"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"Saved your project."}]}]}`), nil
	})
	answer, err := a.complete(context.Background(), chatInput{Messages: []message{{Role: "user", Content: "Save my content strategy as a project"}}})
	if err != nil || answer != "Saved your project." || calls != 2 {
		t.Fatal(answer, err, calls)
	}
	saved := api(t, a, "GET", "/api/workspace", "").Body.String()
	if !strings.Contains(saved, "Keep my chat") || !strings.Contains(saved, "Compare measured retention") {
		t.Fatal(saved)
	}
	history := api(t, a, "GET", "/api/intelligence/actions", "").Body.String()
	if !strings.Contains(history, `"status":"done"`) || strings.Contains(history, a.apiKey) {
		t.Fatal(history)
	}
}

func TestStreamContinuesAfterToolAndCompletesOnce(t *testing.T) {
	a := testApp(t)
	calls := 0
	a.client.Transport = roundTripFunc(func(*http.Request) (*http.Response, error) {
		calls++
		if calls == 1 {
			return fakeResponse(200, "data: "+`{"type":"response.completed","response":{"status":"completed","output":[{"type":"function_call","call_id":"inspect1","name":"vyra_tasks","arguments":"{}"}]}}`+"\n\n"), nil
		}
		return fakeResponse(200, "data: "+`{"type":"response.output_text.delta","delta":"You have no saved tasks."}`+"\n\ndata: "+`{"type":"response.completed","response":{"status":"completed","output":[{"content":[{"type":"output_text","text":"You have no saved tasks."}]}]}}`+"\n\n"), nil
	})
	w := api(t, a, "POST", "/api/chat/stream", `{"messages":[{"role":"user","content":"What tasks do I have?"}]}`)
	if w.Code != 200 || calls != 2 || strings.Count(w.Body.String(), `"type":"done"`) != 1 || !strings.Contains(w.Body.String(), `"type":"action"`) || !strings.Contains(w.Body.String(), "You have no saved tasks.") {
		t.Fatal(calls, w.Body.String())
	}
}

func TestActionAccessAndBackgroundBoundaries(t *testing.T) {
	a := testApp(t)
	event := actionEvent{}
	access := false
	a.prefs.WorkspaceAccess = &access
	if _, err := a.executeTool(context.Background(), chatInput{}, "vyra_save_project", `{"id":"","name":"No","note":"No"}`, &event); err == nil {
		t.Fatal("Disabled access mutated workspace")
	}
	access = true
	for _, name := range []string{"publish", "shell", "read_api_key", "vyra_delete_account"} {
		if _, err := a.executeTool(context.Background(), chatInput{}, name, `{}`, &event); err == nil {
			t.Fatal(name)
		}
	}
	if _, err := validateToolArgs("vyra_read_clip", `{"job_id":"a","filename":"b","path":"../../api-key.dpapi"}`); err == nil {
		t.Fatal("Unknown field accepted")
	}
	if _, err := validateToolArgs("vyra_clips", `{"query":"","limit":null}`); err == nil {
		t.Fatal("Null integer accepted")
	}
	for name, args := range map[string]string{"vyra_task_action": `{"id":"a","action":"run"}`, "vyra_save_task": `{"id":"","name":"Recursive","prompt":"spawn","schedule":"interval","intervalMinutes":60,"nextRun":"","enabled":true,"maxRuns":2}`, "vyra_open": `{"view":"clips","draft_id":""}`} {
		if _, err := a.executeTool(context.Background(), chatInput{Background: true}, name, args, &event); err == nil {
			t.Fatal("Background action allowed", name)
		}
	}
	if _, err := a.clipsAction(context.Background(), "publish", nil); err == nil {
		t.Fatal("Publish reachable through tool proxy")
	}
}

func TestRegisteredToolsAreStrictAndNoCredentialActions(t *testing.T) {
	for _, tool := range intelligenceTools() {
		schema := tool["parameters"].(map[string]any)
		if tool["strict"] != true || schema["additionalProperties"] != false || len(schema["required"].([]string)) != len(schema["properties"].(map[string]any)) {
			t.Fatal(tool["name"])
		}
		name := tool["name"].(string)
		if strings.Contains(name, "secret") || strings.Contains(name, "credential") || strings.Contains(name, "submit") {
			t.Fatal(name)
		}
	}
}
