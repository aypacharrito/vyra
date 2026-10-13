package main

import (
	"context"
	"crypto/rand"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

//go:embed web/*
var content embed.FS

var version = "1.1.0"

type app struct {
	mu       sync.RWMutex
	apiKey   string
	verified bool
	model    string
	csrf     string
	server   *http.Server
	worker   *exec.Cmd
	client   *http.Client
}

func token() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b)
}
func newApp() *app {
	a := &app{csrf: token(), model: "gpt-5-mini", client: &http.Client{Timeout: 80 * time.Second}}
	a.apiKey = os.Getenv("OPENAI_API_KEY")
	if a.apiKey == "" {
		if k, err := loadKey(); err == nil {
			a.apiKey = k
		}
	}
	return a
}
func (a *app) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		b, err := content.ReadFile("web/index.html")
		if err != nil {
			http.Error(w, "UI missing", 500)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Write([]byte(strings.ReplaceAll(string(b), "__VYRA_SESSION__", a.csrf)))
	})
	mux.HandleFunc("GET /app.js", func(w http.ResponseWriter, r *http.Request) {
		serveEmbedded(w, "web/app.js", "text/javascript; charset=utf-8")
	})
	mux.HandleFunc("GET /styles.css", func(w http.ResponseWriter, r *http.Request) {
		serveEmbedded(w, "web/styles.css", "text/css; charset=utf-8")
	})
	mux.HandleFunc("GET /api/status", func(w http.ResponseWriter, r *http.Request) {
		a.mu.RLock()
		configured := a.apiKey != ""
		verified := a.verified
		model := a.model
		a.mu.RUnlock()
		writeJSON(w, 200, map[string]any{"version": version, "local": true, "openai": configured, "verified": verified, "model": model, "worker": workerAvailable()})
	})
	mux.HandleFunc("POST /api/settings", func(w http.ResponseWriter, r *http.Request) {
		var v struct {
			Key     string `json:"key"`
			Model   string `json:"model"`
			Persist bool   `json:"persist"`
		}
		if !parseBody(w, r, &v) {
			return
		}
		key := strings.TrimSpace(v.Key)
		if key != "" && (!strings.HasPrefix(key, "sk-") || len(key) < 20 || len(key) > 300) {
			writeJSON(w, 400, map[string]string{"error": "Enter a valid OpenAI API key beginning with sk-."})
			return
		}
		a.mu.Lock()
		if key != "" {
			a.apiKey = key
			a.verified = false
		}
		if v.Model != "" {
			if v.Model != "gpt-5-mini" && v.Model != "gpt-4o-mini" {
				a.mu.Unlock()
				writeJSON(w, 400, map[string]string{"error": "Unsupported model selection."})
				return
			}
			a.model = v.Model
		}
		actual := a.apiKey
		a.mu.Unlock()
		if v.Persist && key != "" {
			if err := saveKey(actual); err != nil {
				writeJSON(w, 500, map[string]string{"error": "Could not encrypt key: " + err.Error()})
				return
			}
		}
		writeJSON(w, 200, map[string]any{"saved": true, "openai": actual != ""})
	})
	mux.HandleFunc("DELETE /api/settings/key", func(w http.ResponseWriter, r *http.Request) {
		a.mu.Lock()
		a.apiKey = ""
		a.verified = false
		a.mu.Unlock()
		_ = deleteKey()
		writeJSON(w, 200, map[string]bool{"removed": true})
	})
	mux.HandleFunc("POST /api/chat", a.chat)
	mux.HandleFunc("POST /api/openai/test", a.openAITest)
	mux.HandleFunc("GET /api/updates", func(w http.ResponseWriter, r *http.Request) { writeJSON(w, 200, updates.result()) })
	mux.HandleFunc("POST /api/updates/check", a.checkUpdates)
	mux.HandleFunc("POST /api/updates/install", a.installUpdate)
	mux.HandleFunc("POST /api/clips/launch", a.launchClips)
	mux.HandleFunc("GET /api/clips/status", func(w http.ResponseWriter, r *http.Request) {
		client := http.Client{Timeout: 1200 * time.Millisecond}
		resp, err := client.Get("http://127.0.0.1:8765/api/status")
		running := err == nil && resp.StatusCode == 200
		if resp != nil {
			resp.Body.Close()
		}
		writeJSON(w, 200, map[string]any{"running": running, "installed": workerAvailable()})
	})
	mux.HandleFunc("POST /api/quit", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]bool{"ok": true})
		go func() { time.Sleep(250 * time.Millisecond); a.server.Shutdown(context.Background()) }()
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host, _, err := net.SplitHostPort(r.Host)
		if err != nil {
			host = r.Host
		}
		if host != "localhost" && host != "127.0.0.1" {
			http.Error(w, "Local application only", 403)
			return
		}
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
		if r.Method == "POST" || r.Method == "DELETE" || r.Method == "PUT" {
			origin := r.Header.Get("Origin")
			if origin != "" && origin != "http://"+r.Host {
				http.Error(w, "Origin rejected", 403)
				return
			}
			if r.Header.Get("X-VYRA-SESSION") != a.csrf {
				http.Error(w, "Session rejected", 403)
				return
			}
			r.Body = http.MaxBytesReader(w, r.Body, 150000)
		}
		mux.ServeHTTP(w, r)
	})
}
func serveEmbedded(w http.ResponseWriter, path, typ string) {
	v, err := content.ReadFile(path)
	if err != nil {
		http.Error(w, "Not found", 404)
		return
	}
	w.Header().Set("Content-Type", typ)
	w.Write(v)
}
func parseBody(w http.ResponseWriter, r *http.Request, v any) bool {
	if err := json.NewDecoder(r.Body).Decode(v); err != nil {
		writeJSON(w, 400, map[string]string{"error": "Invalid request data"})
		return false
	}
	return true
}
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

type message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

func (a *app) chat(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Messages []message `json:"messages"`
		Model    string    `json:"model"`
	}
	if !parseBody(w, r, &body) {
		return
	}
	a.mu.RLock()
	key := a.apiKey
	model := a.model
	a.mu.RUnlock()
	if key == "" {
		writeJSON(w, 503, map[string]string{"error": "Connect an OpenAI API key in Settings to activate VYRA chat."})
		return
	}
	if len(body.Messages) == 0 || len(body.Messages) > 40 {
		writeJSON(w, 400, map[string]string{"error": "Provide between 1 and 40 messages."})
		return
	}
	msgs := make([]map[string]string, 0, len(body.Messages))
	for _, msg := range body.Messages {
		if msg.Role != "user" && msg.Role != "assistant" {
			writeJSON(w, 400, map[string]string{"error": "Unknown message role."})
			return
		}
		if len(msg.Content) > 15000 {
			writeJSON(w, 400, map[string]string{"error": "Message too long."})
			return
		}
		msgs = append(msgs, map[string]string{"role": msg.Role, "content": msg.Content})
	}
	if len(msgs) > 16 {
		msgs = msgs[len(msgs)-16:]
	}
	reqBody := map[string]any{"model": model, "input": msgs, "store": false, "max_output_tokens": 1800, "instructions": "You are VYRA, a focused, capable personal AI assistant in a Windows desktop workspace. Be accurate, thoughtful, clear, helpful, practical. Help with coding, content creation, planning, analysis, and writing. Be transparent about limitations: you cannot perform actions on external services unless a connected tool exists. You are not OpenAI or any other product; you are powered by OpenAI models."}
	raw, _ := json.Marshal(reqBody)
	req, err := http.NewRequestWithContext(r.Context(), "POST", "https://api.openai.com/v1/responses", strings.NewReader(string(raw)))
	if err != nil {
		writeJSON(w, 502, map[string]string{"error": "Could not create AI request."})
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+key)
	resp, err := a.client.Do(req)
	if err != nil {
		writeJSON(w, 502, map[string]string{"error": "OpenAI connection failed. Check your internet connection."})
		return
	}
	defer resp.Body.Close()
	result, _ := io.ReadAll(io.LimitReader(resp.Body, 1500000))
	if resp.StatusCode != 200 {
		var failure struct {
			Error struct {
				Message string `json:"message"`
			} `json:"error"`
		}
		_ = json.Unmarshal(result, &failure)
		e := failure.Error.Message
		if e == "" {
			e = fmt.Sprintf("OpenAI returned HTTP %d", resp.StatusCode)
		}
		if len(e) > 350 {
			e = e[:350]
		}
		writeJSON(w, 502, map[string]string{"error": e})
		return
	}
	var value struct {
		OutputText string `json:"output_text"`
		Output     []struct {
			Content []struct {
				Type string `json:"type"`
				Text string `json:"text"`
			} `json:"content"`
		} `json:"output"`
	}
	if err := json.Unmarshal(result, &value); err != nil {
		writeJSON(w, 502, map[string]string{"error": "Invalid AI response."})
		return
	}
	answer := value.OutputText
	for _, out := range value.Output {
		for _, part := range out.Content {
			if part.Type == "output_text" {
				if answer != "" {
					answer += "\n"
				}
				answer += part.Text
			}
		}
	}
	if strings.TrimSpace(answer) == "" {
		writeJSON(w, 502, map[string]string{"error": "AI returned no text."})
		return
	}
	writeJSON(w, 200, map[string]string{"answer": answer, "model": model})
}
func workerDirectory() string {
	path, _ := os.Executable()
	return filepath.Join(filepath.Dir(path), "clips-worker")
}
func workerAvailable() bool {
	p := filepath.Join(workerDirectory(), "server.py")
	i, e := os.Stat(p)
	return e == nil && !i.IsDir()
}
func (a *app) launchClips(w http.ResponseWriter, r *http.Request) {
	if !workerAvailable() {
		writeJSON(w, 404, map[string]string{"error": "Clips worker isn't beside this EXE. Extract the full VYRA package first."})
		return
	}
	client := http.Client{Timeout: 800 * time.Millisecond}
	resp, err := client.Get("http://127.0.0.1:8765/api/status")
	if err == nil {
		resp.Body.Close()
		if resp.StatusCode == 200 {
			writeJSON(w, 200, map[string]string{"url": "http://127.0.0.1:8765", "status": "running"})
			return
		}
	}
	a.mu.RLock()
	key := a.apiKey
	a.mu.RUnlock()
	if key == "" {
		writeJSON(w, 503, map[string]string{"error": "Connect your OpenAI key in Settings before opening the Clips worker."})
		return
	}
	exe, err := exec.LookPath("python")
	if err != nil {
		exe, err = exec.LookPath("py")
		if err != nil {
			writeJSON(w, 503, map[string]string{"error": "Python is required for VYRA Clips. Install Python 3.11+ and run SETUP_CLIPS.bat once."})
			return
		}
	}
	args := []string{"-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8765"}
	if strings.EqualFold(filepath.Base(exe), "py.exe") {
		args = append([]string{"-3"}, args...)
	}
	cmd := exec.Command(exe, args...)
	cmd.Dir = workerDirectory()
	cmd.Env = append(os.Environ(), "OPENAI_API_KEY="+key)
	hideWorker(cmd)
	if err := cmd.Start(); err != nil {
		writeJSON(w, 502, map[string]string{"error": "Could not start Clips worker: " + err.Error()})
		return
	}
	a.mu.Lock()
	a.worker = cmd
	a.mu.Unlock()
	go cmd.Wait()
	for i := 0; i < 18; i++ {
		time.Sleep(400 * time.Millisecond)
		c := http.Client{Timeout: 350 * time.Millisecond}
		re, e := c.Get("http://127.0.0.1:8765/api/status")
		if e == nil {
			re.Body.Close()
			if re.StatusCode == 200 {
				writeJSON(w, 200, map[string]string{"url": "http://127.0.0.1:8765", "status": "started"})
				return
			}
		}
	}
	writeJSON(w, 503, map[string]string{"error": "Clips could not start. Run SETUP_CLIPS.bat, verify Python dependencies and FFmpeg, then retry."})
}
func main() {
	a := newApp()
	l, err := net.Listen("tcp", "127.0.0.1:48791")
	if err != nil {
		showExisting()
		return
	}
	defer l.Close()
	a.server = &http.Server{Handler: a.routes(), ReadHeaderTimeout: 5 * time.Second}
	go openDesktop("http://127.0.0.1:48791/")
	a.startUpdateChecks()
	if err := a.server.Serve(l); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Println(err)
	}
}
