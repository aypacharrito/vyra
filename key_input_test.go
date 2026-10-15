package main

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestKeyCopyPasteFormats(t *testing.T) {
	key := "sk-proj-" + strings.Repeat("synthetic", 80)
	for _, input := range []string{key, " \r\n" + key + "\t", `"` + key + `"`, "‘" + key + "’", "Bearer " + key, "export OPENAI_API_KEY='" + key + "'", "\ufeff" + key[:40] + "\u200b" + key[40:]} {
		normalized, err := normalizeAPIKey(input)
		if err != nil || normalized != key {
			t.Fatal("A supported paste format was rejected")
		}
	}
}
func TestHiddenKeysAndNonKeysAreRejectedPrivately(t *testing.T) {
	for _, key := range []string{"sk-proj-abc...xyz", "sk-proj-abc…xyz", "sk-proj-*************", "project_12345678901234567890", "sk-this contains a space", "\"\"", "sk-bad\nsecond-line-value"} {
		_, err := normalizeAPIKey(key)
		if err == nil {
			t.Fatal("Accepted a hidden or incomplete key")
		}
		if strings.Contains(err.Error(), key) {
			t.Fatal("Error included credential input")
		}
	}
}
func TestWrappedKeyIsEncryptedAndSurvivesRestart(t *testing.T) {
	a := testApp(t)
	key := "sk-proj-" + strings.Repeat("synthetic", 80)
	body, _ := json.Marshal(map[string]any{"key": "Bearer '" + key + "'", "persist": true, "model": "gpt-5-mini"})
	w := api(t, a, "POST", "/api/settings", string(body))
	if w.Code != 200 {
		t.Fatal(w.Code)
	}
	b := newApp()
	if b.apiKey != key {
		t.Fatal("Saved credential did not survive restart")
	}
	raw, err := os.ReadFile(keyFile())
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), key) {
		t.Fatal("Credential saved as plaintext")
	}
}
