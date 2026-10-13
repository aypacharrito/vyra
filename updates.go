package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
)

const updateManifestURL = "https://vyra-five-lac.vercel.app/updates/latest.json"

type updateManifest struct {
	Version string `json:"version"`
	URL     string `json:"url"`
	SHA256  string `json:"sha256"`
	Notes   string `json:"notes"`
}

type updateState struct {
	mu          sync.RWMutex
	lastChecked time.Time
	errorText   string
	manifest    updateManifest
}

var updates = &updateState{}
var numericVersion = regexp.MustCompile(`^\d+\.\d+\.\d+$`)
var sha256Pattern = regexp.MustCompile(`^[a-f0-9]{64}$`)

func newerVersion(remote, current string) bool {
	if !numericVersion.MatchString(remote) || !numericVersion.MatchString(current) {
		return false
	}
	var a, b, c, x, y, z int
	fmt.Sscanf(remote, "%d.%d.%d", &a, &b, &c)
	fmt.Sscanf(current, "%d.%d.%d", &x, &y, &z)
	if a != x {
		return a > x
	}
	if b != y {
		return b > y
	}
	return c > z
}
func validManifest(m updateManifest) bool {
	u, err := url.Parse(m.URL)
	if err != nil || u.Scheme != "https" || u.Host != "vyra-five-lac.vercel.app" || !strings.HasPrefix(u.Path, "/downloads/") || !strings.HasSuffix(u.Path, "/VYRA-Setup.exe") || u.User != nil || u.Fragment != "" {
		return false
	}
	return numericVersion.MatchString(m.Version) && sha256Pattern.MatchString(m.SHA256)
}
func (u *updateState) check(ctx context.Context) error {
	request, err := http.NewRequestWithContext(ctx, "GET", updateManifestURL, nil)
	if err != nil {
		return err
	}
	request.Header.Set("User-Agent", "VYRA-Desktop/"+version)
	client := &http.Client{Timeout: 7 * time.Second}
	resp, err := client.Do(request)
	if err != nil {
		u.setError("Update server not reachable")
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		u.setError("Update server returned an error")
		return fmt.Errorf("update server status %d", resp.StatusCode)
	}
	var m updateManifest
	if err = json.NewDecoder(io.LimitReader(resp.Body, 4096)).Decode(&m); err != nil || !validManifest(m) {
		u.setError("Update manifest invalid")
		return errors.New("invalid update manifest")
	}
	u.mu.Lock()
	u.manifest = m
	u.lastChecked = time.Now()
	u.errorText = ""
	u.mu.Unlock()
	return nil
}
func (u *updateState) setError(s string) {
	u.mu.Lock()
	u.errorText = s
	u.lastChecked = time.Now()
	u.mu.Unlock()
}
func (u *updateState) result() map[string]any {
	u.mu.RLock()
	defer u.mu.RUnlock()
	checked := ""
	if !u.lastChecked.IsZero() {
		checked = u.lastChecked.UTC().Format(time.RFC3339)
	}
	return map[string]any{"version": version, "latest": u.manifest.Version, "available": newerVersion(u.manifest.Version, version), "notes": u.manifest.Notes, "lastChecked": checked, "error": u.errorText, "automaticChecks": true, "automaticInstall": false}
}
func (a *app) checkUpdates(w http.ResponseWriter, r *http.Request) {
	if err := updates.check(r.Context()); err != nil {
		writeJSON(w, 502, updates.result())
		return
	}
	writeJSON(w, 200, updates.result())
}
func (a *app) installUpdate(w http.ResponseWriter, r *http.Request) {
	if !a.installMu.TryLock() {
		writeJSON(w, 409, map[string]string{"error": "An update is already being downloaded."})
		return
	}
	defer a.installMu.Unlock()
	updates.mu.RLock()
	m := updates.manifest
	updates.mu.RUnlock()
	if !newerVersion(m.Version, version) || !validManifest(m) {
		writeJSON(w, 409, map[string]string{"error": "No verified newer installer is available. Check for updates first."})
		return
	}
	downloadPath := filepath.Join(os.TempDir(), "VYRA-Updates", "VYRA-Setup-"+m.Version+".exe")
	if err := os.MkdirAll(filepath.Dir(downloadPath), 0700); err != nil {
		writeJSON(w, 500, map[string]string{"error": "Cannot prepare update folder"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Minute)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", m.URL, nil)
	response, err := (&http.Client{Timeout: 3 * time.Minute}).Do(req)
	if err != nil {
		writeJSON(w, 502, map[string]string{"error": "Update download failed"})
		return
	}
	defer response.Body.Close()
	if response.StatusCode != 200 || response.ContentLength > 100*1024*1024 {
		writeJSON(w, 502, map[string]string{"error": "Unexpected update download"})
		return
	}
	tmp := downloadPath + ".part"
	out, err := os.OpenFile(tmp, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0600)
	if err != nil {
		writeJSON(w, 500, map[string]string{"error": "Cannot write update file"})
		return
	}
	digest := sha256.New()
	size, copyErr := io.Copy(io.MultiWriter(out, digest), io.LimitReader(response.Body, 100*1024*1024+1))
	closeErr := out.Close()
	if copyErr != nil || closeErr != nil || size < 500000 || size > 100*1024*1024 || hex.EncodeToString(digest.Sum(nil)) != m.SHA256 {
		os.Remove(tmp)
		writeJSON(w, 502, map[string]string{"error": "Update integrity verification failed. Nothing was installed."})
		return
	}
	if err = os.Rename(tmp, downloadPath); err != nil {
		os.Remove(tmp)
		writeJSON(w, 500, map[string]string{"error": "Cannot stage verified update"})
		return
	}
	cmd := exec.Command(downloadPath, "--auto-update")
	hideWorker(cmd)
	if err = cmd.Start(); err != nil {
		writeJSON(w, 502, map[string]string{"error": "Couldn't launch update installer"})
		return
	}
	writeJSON(w, 200, map[string]any{"installing": true, "version": m.Version})
	go func() { time.Sleep(700 * time.Millisecond); _ = a.server.Shutdown(context.Background()) }()
}
func (a *app) openAITest(w http.ResponseWriter, r *http.Request) {
	a.mu.RLock()
	key := a.apiKey
	model := a.model
	a.mu.RUnlock()
	if key == "" {
		writeJSON(w, 400, map[string]string{"error": "Save your OpenAI API key in Settings first."})
		return
	}
	if !validTextModel(model) {
		writeJSON(w, 400, map[string]string{"error": "Choose a supported model"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 12*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", "https://api.openai.com/v1/models/"+url.PathEscape(model), nil)
	req.Header.Set("Authorization", "Bearer "+key)
	response, err := a.client.Do(req)
	if err != nil {
		writeJSON(w, 502, map[string]string{"error": "Could not reach OpenAI. Check internet access."})
		return
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		// Never echo raw provider error, which might include secrets or account identifiers.
		msg := "OpenAI did not accept this key or model access. Check your API key, project and billing."
		if response.StatusCode == 401 {
			msg = "OpenAI rejected the API key (401). Create a new key in your OpenAI API project."
		}
		if response.StatusCode == 403 {
			msg = "OpenAI access denied (403). Check project permissions."
		}
		if response.StatusCode == 404 {
			msg = "Selected model not available to this API project."
		}
		writeJSON(w, 502, map[string]string{"error": msg})
		return
	}
	_ = ctx
	a.mu.Lock()
	if a.apiKey == key && a.model == model {
		a.verified = true
	}
	a.mu.Unlock()
	writeJSON(w, 200, map[string]any{"verified": true, "model": model, "message": "Connected to OpenAI. You can now start a chat. This check doesn't verify remaining credit or billing limits."})
}
func (a *app) startUpdateChecks() {
	go func() {
		time.Sleep(3 * time.Second)
		for {
			ctx, cancel := context.WithTimeout(context.Background(), 9*time.Second)
			_ = updates.check(ctx)
			cancel()
			time.Sleep(6 * time.Hour)
		}
	}()
}
