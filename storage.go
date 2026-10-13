package main

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

type preferences struct {
	Model        string `json:"model"`
	Instructions string `json:"instructions"`
	SpeakReplies bool   `json:"speakReplies"`
	Language     string `json:"language"`
	Voice        string `json:"voice"`
}

func userDataDir() string {
	if path := os.Getenv("VYRA_DATA_DIR"); path != "" {
		return path
	}
	root, err := os.UserConfigDir()
	if err != nil {
		root = os.TempDir()
	}
	return filepath.Join(root, "VYRA")
}

func atomicJSON(path string, value any) error {
	raw, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".vyra-*.tmp")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if err = f.Chmod(0600); err == nil {
		_, err = f.Write(raw)
	}
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Rename(name, path)
}

var modelName = regexp.MustCompile(`^(gpt-[a-zA-Z0-9][a-zA-Z0-9._-]{0,100}|o[1-9][a-zA-Z0-9._-]{0,100})$`)

func validTextModel(s string) bool {
	if !modelName.MatchString(s) {
		return false
	}
	for _, term := range []string{"audio", "transcribe", "realtime", "tts", "image", "live-", "moderation", "embedding"} {
		if strings.Contains(strings.ToLower(s), term) {
			return false
		}
	}
	return true
}

func (a *app) loadPreferences() {
	a.prefs = preferences{Model: a.model, Language: "en-US"}
	raw, err := os.ReadFile(filepath.Join(a.dataDir, "preferences.json"))
	if err == nil {
		var p preferences
		if json.Unmarshal(raw, &p) == nil && validTextModel(p.Model) && len(p.Instructions) <= 4000 {
			a.prefs = p
			a.model = p.Model
		}
	}
}
func (a *app) getPreferences(w http.ResponseWriter, r *http.Request) {
	a.mu.RLock()
	p := a.prefs
	a.mu.RUnlock()
	writeJSON(w, 200, p)
}
func (a *app) setPreferences(w http.ResponseWriter, r *http.Request) {
	var p preferences
	if !parseBody(w, r, &p) {
		return
	}
	p.Model = strings.TrimSpace(p.Model)
	if !validTextModel(p.Model) || len(p.Instructions) > 4000 || len(p.Language) > 35 || len(p.Voice) > 150 {
		writeJSON(w, 400, map[string]string{"error": "Choose a text model and keep personal instructions under 4,000 characters."})
		return
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if err := atomicJSON(filepath.Join(a.dataDir, "preferences.json"), p); err != nil {
		writeJSON(w, 500, map[string]string{"error": "Could not save preferences on this device."})
		return
	}
	a.prefs = p
	if a.model != p.Model {
		a.verified = false
	}
	a.model = p.Model
	writeJSON(w, 200, p)
}

// The workspace file survives browser data resets and installer replacements.
// Read only from a fixed app-owned path. No caller-supplied filesystem paths.
func (a *app) getWorkspace(w http.ResponseWriter, r *http.Request) {
	a.mu.RLock()
	defer a.mu.RUnlock()
	raw, err := os.ReadFile(filepath.Join(a.dataDir, "workspace.json"))
	if errors.Is(err, os.ErrNotExist) {
		writeJSON(w, 200, map[string]any{})
		return
	}
	if err != nil || !json.Valid(raw) {
		writeJSON(w, 500, map[string]string{"error": "Saved workspace could not be read. Your file has been preserved."})
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write(raw)
}
func (a *app) putWorkspace(w http.ResponseWriter, r *http.Request) {
	raw, err := io.ReadAll(r.Body)
	if err != nil {
		writeJSON(w, 413, map[string]string{"error": "Workspace is too large. Export older conversations."})
		return
	}
	var obj struct {
		Chats     []json.RawMessage `json:"chats"`
		Projects  []json.RawMessage `json:"projects"`
		Active    string            `json:"active"`
		ProjectID string            `json:"projectId"`
		Mode      string            `json:"mode"`
	}
	if json.Unmarshal(raw, &obj) != nil || len(obj.Chats) > 80 || len(obj.Projects) > 100 || len(obj.Active) > 100 {
		writeJSON(w, 400, map[string]string{"error": "Invalid workspace backup."})
		return
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if err = atomicJSON(filepath.Join(a.dataDir, "workspace.json"), obj); err != nil {
		writeJSON(w, 500, map[string]string{"error": "Could not save workspace on this device."})
		return
	}
	writeJSON(w, 200, map[string]bool{"saved": true})
}
