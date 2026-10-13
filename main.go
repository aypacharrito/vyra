package main

import (
	"context"
	"crypto/rand"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
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

var version = "1.2.1"

type app struct {
	mu        sync.RWMutex
	apiKey    string
	verified  bool
	model     string
	csrf      string
	server    *http.Server
	worker    *exec.Cmd
	client    *http.Client
	dataDir   string
	prefs     preferences
	tasks     *taskStore
	aiSlots   chan struct{}
	launchMu  sync.Mutex
	installMu sync.Mutex
}

func token() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b)
}
func newApp() *app {
	a := &app{csrf: token(), model: "gpt-5-mini", client: &http.Client{Timeout: 3 * time.Minute}, dataDir: userDataDir(), aiSlots: make(chan struct{}, 2)}
	a.loadPreferences()
	a.tasks = openTaskStore(filepath.Join(a.dataDir, "tasks.json"))
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
	for path, mime := range map[string]string{"icon.svg": "image/svg+xml", "icon.png": "image/png", "favicon.ico": "image/x-icon"} {
		mux.HandleFunc("GET /"+path, func(w http.ResponseWriter, r *http.Request) {
			serveEmbedded(w, "web/"+path, mime)
		})
	}
	mux.HandleFunc("GET /api/status", func(w http.ResponseWriter, r *http.Request) {
		a.mu.RLock()
		configured := a.apiKey != ""
		verified := a.verified
		model := a.model
		a.mu.RUnlock()
		writeJSON(w, 200, map[string]any{"version": version, "local": true, "openai": configured, "verified": verified, "model": model, "worker": workerAvailable()})
	})
	mux.HandleFunc("POST /api/settings", a.setConnection)
	mux.HandleFunc("DELETE /api/settings/key", func(w http.ResponseWriter, r *http.Request) {
		if err := deleteKey(); err != nil && !errors.Is(err, os.ErrNotExist) {
			writeJSON(w, 500, map[string]string{"error": "Could not remove the saved key. Check this Windows account's access."})
			return
		}
		a.mu.Lock()
		a.apiKey = ""
		a.verified = false
		a.mu.Unlock()
		writeJSON(w, 200, map[string]bool{"removed": true})
	})
	mux.HandleFunc("POST /api/chat", a.chat)
	mux.HandleFunc("POST /api/chat/stream", a.streamChat)
	mux.HandleFunc("GET /api/models", a.models)
	mux.HandleFunc("GET /api/preferences", a.getPreferences)
	mux.HandleFunc("PUT /api/preferences", a.setPreferences)
	mux.HandleFunc("GET /api/workspace", a.getWorkspace)
	mux.HandleFunc("PUT /api/workspace", a.putWorkspace)
	mux.HandleFunc("POST /api/voice/transcribe", a.transcribe)
	mux.HandleFunc("GET /api/tasks", a.listTasks)
	mux.HandleFunc("POST /api/tasks", a.createTask)
	mux.HandleFunc("PUT /api/tasks/{id}", a.editTask)
	mux.HandleFunc("DELETE /api/tasks/{id}", a.deleteTask)
	mux.HandleFunc("POST /api/tasks/{id}/run", a.runTask)
	mux.HandleFunc("POST /api/tasks/{id}/cancel", a.cancelTask)
	mux.HandleFunc("POST /api/openai/test", a.openAITest)
	mux.HandleFunc("GET /api/updates", func(w http.ResponseWriter, r *http.Request) { writeJSON(w, 200, updates.result()) })
	mux.HandleFunc("POST /api/updates/check", a.checkUpdates)
	mux.HandleFunc("POST /api/updates/install", a.installUpdate)
	mux.HandleFunc("POST /api/clips/launch", a.launchClips)
	mux.HandleFunc("POST /api/clips/setup", a.setupClips)
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
		w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
		w.Header().Set("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
		if origin := r.Header.Get("Origin"); origin != "" && origin != "http://"+r.Host {
			http.Error(w, "Origin rejected", 403)
			return
		}
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
			limit := int64(2 * 1024 * 1024)
			if r.URL.Path == "/api/voice/transcribe" {
				limit = 12 * 1024 * 1024
			}
			r.Body = http.MaxBytesReader(w, r.Body, limit)
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
	if !a.launchMu.TryLock() {
		writeJSON(w, 409, map[string]string{"error": "Clips Studio is starting. Wait a moment and retry."})
		return
	}
	defer a.launchMu.Unlock()
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
	exe := filepath.Join(workerDirectory(), ".venv", "Scripts", "python.exe")
	_, err = os.Stat(exe)
	if err != nil {
		exe, err = exec.LookPath("python")
	}
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

func (a *app) setupClips(w http.ResponseWriter, r *http.Request) {
	if err := openClipsSetup(); err != nil {
		writeJSON(w, 503, map[string]string{"error": "Could not open Clips setup. Run SETUP_CLIPS.bat from your VYRA installation folder."})
		return
	}
	writeJSON(w, 200, map[string]bool{"started": true})
}
func main() {
	a := newApp()
	port := os.Getenv("VYRA_PORT")
	if port == "" {
		port = "48791"
	}
	l, err := net.Listen("tcp", "127.0.0.1:"+port)
	if err != nil {
		showExisting()
		return
	}
	defer l.Close()
	a.server = &http.Server{Handler: a.routes(), ReadHeaderTimeout: 5 * time.Second}
	if os.Getenv("VYRA_HEADLESS") != "1" {
		go openDesktop("http://" + l.Addr().String() + "/")
	}
	a.startUpdateChecks()
	a.startTasks()
	defer a.stopTasks()
	if err := a.server.Serve(l); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Println(err)
	}
}
