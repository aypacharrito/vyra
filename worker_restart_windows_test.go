//go:build windows

package main

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// Run the actual Windows restart path against a disposable HTTP/process fixture.
// A copied test executable supplies the worker protocol without needing Python,
// real accounts, uploads or an existing VYRA installation.
func TestMain(m *testing.M) {
	if os.Getenv("VYRA_TEST_RESTART_HELPER") == "1" {
		port := ""
		for i, arg := range os.Args {
			if arg == "--port" && i+1 < len(os.Args) {
				port = os.Args[i+1]
			}
		}
		mux := http.NewServeMux()
		mux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
			json.NewEncoder(w).Encode(map[string]string{"version": "0.6.5", "render_engine": "FFmpeg", "post_safety": "consent per destination"})
		})
		mux.HandleFunc("/api/queue", func(w http.ResponseWriter, r *http.Request) {
			if os.Getenv("VYRA_TEST_QUEUE_ERROR") == "1" {
				http.Error(w, "broken delivery metadata", 500)
				return
			}
			if os.Getenv("VYRA_TEST_RESTART_BUSY") == "1" {
				fmt.Fprint(w, `[{"status":"sending"}]`)
			} else {
				fmt.Fprint(w, `[]`)
			}
		})
		if err := http.ListenAndServe("127.0.0.1:"+port, mux); err != nil {
			os.Exit(2)
		}
		return
	}
	os.Exit(m.Run())
}

func TestWindowsWorkerRecoveryWithRealProcess(t *testing.T) {
	for _, scenario := range []string{"idle_batch", "idle_desktop", "uploading", "unrecognized_command", "queue_error", "recover_queue_error", "recover_uploading"} {
		t.Run(scenario, func(t *testing.T) {
			executable, err := os.Executable()
			if err != nil {
				t.Fatal(err)
			}
			bytes, err := os.ReadFile(executable)
			if err != nil {
				t.Fatal(err)
			}
			helper := filepath.Join(t.TempDir(), "python.exe")
			if err = os.WriteFile(helper, bytes, 0700); err != nil {
				t.Fatal(err)
			}
			listener, err := net.Listen("tcp4", "127.0.0.1:0")
			if err != nil {
				t.Fatal(err)
			}
			port := listener.Addr().(*net.TCPAddr).Port
			listener.Close()
			args := []string{"-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", strconv.Itoa(port)}
			if scenario == "idle_desktop" {
				args = append(args, "--no-access-log")
			}
			if scenario == "unrecognized_command" {
				args = append(args, "--reload")
			}
			cmd := exec.Command(helper, args...)
			cmd.Env = append(os.Environ(), "VYRA_TEST_RESTART_HELPER=1")
			if strings.Contains(scenario, "uploading") {
				cmd.Env = append(cmd.Env, "VYRA_TEST_RESTART_BUSY=1")
			}
			if strings.Contains(scenario, "queue_error") {
				cmd.Env = append(cmd.Env, "VYRA_TEST_QUEUE_ERROR=1")
			}
			if err = cmd.Start(); err != nil {
				t.Fatal(err)
			}
			defer func() { cmd.Process.Kill(); cmd.Wait() }()
			client := &http.Client{Timeout: 200 * time.Millisecond}
			url := "http://127.0.0.1:" + strconv.Itoa(port) + "/api/status"
			ready := false
			for i := 0; i < 100; i++ {
				response, e := client.Get(url)
				if e == nil {
					response.Body.Close()
					ready = true
					break
				}
				time.Sleep(30 * time.Millisecond)
			}
			if !ready {
				t.Fatal("fixture did not start")
			}
			err = stopLegacyWorkerWithRecovery(port, strings.HasPrefix(scenario, "recover_"))
			if strings.HasPrefix(scenario, "idle_") || scenario == "recover_queue_error" {
				if err != nil {
					t.Fatal(err)
				}
				if pid, e := listeningWorkerPID(port); e != nil || pid != 0 {
					t.Fatalf("listener still present: %d / %v", pid, e)
				}
			} else {
				if err == nil {
					t.Fatal("unsafe replacement was accepted")
				}
				if scenario == "uploading" && !strings.Contains(err.Error(), "uploading") {
					t.Fatal(err)
				}
				response, e := client.Get(url)
				if e != nil {
					t.Fatal("protected worker was stopped", e)
				}
				response.Body.Close()
			}
		})
	}
}
