package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

type task struct {
	ID              string    `json:"id"`
	Name            string    `json:"name"`
	Prompt          string    `json:"prompt"`
	Context         string    `json:"context"`
	Mode            string    `json:"mode"`
	Model           string    `json:"model"`
	Schedule        string    `json:"schedule"`
	IntervalMinutes int       `json:"intervalMinutes"`
	NextRun         time.Time `json:"nextRun"`
	Enabled         bool      `json:"enabled"`
	MaxRuns         int       `json:"maxRuns"`
	RunCount        int       `json:"runCount"`
	Created         time.Time `json:"created"`
}
type taskRun struct {
	ID       string    `json:"id"`
	TaskID   string    `json:"taskId"`
	Name     string    `json:"name"`
	Model    string    `json:"model"`
	Status   string    `json:"status"`
	Started  time.Time `json:"started"`
	Finished time.Time `json:"finished"`
	Result   string    `json:"result"`
	Error    string    `json:"error"`
}
type taskStore struct {
	mu        sync.Mutex
	path      string
	Tasks     []task    `json:"tasks"`
	Runs      []taskRun `json:"runs"`
	loadError string
	cancel    map[string]context.CancelFunc
	stop      context.CancelFunc
	wg        sync.WaitGroup
}

func openTaskStore(path string) *taskStore {
	s := &taskStore{path: path, Tasks: []task{}, Runs: []taskRun{}, cancel: map[string]context.CancelFunc{}}
	raw, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return s
	}
	if err != nil || json.Unmarshal(raw, s) != nil {
		s.Tasks = []task{}
		s.Runs = []taskRun{}
		s.loadError = "Task storage could not be read. The original file has been preserved. Restore a backup before scheduling more work."
		return s
	}
	changed := false
	// A crash might happen after a billable call. Never silently retry it.
	for i := range s.Runs {
		if s.Runs[i].Status == "running" {
			s.Runs[i].Status = "interrupted"
			s.Runs[i].Error = "VYRA closed during this run. Review before running again."
			s.Runs[i].Finished = time.Now()
			changed = true
			for j := range s.Tasks {
				if s.Tasks[j].ID == s.Runs[i].TaskID {
					s.Tasks[j].Enabled = false
				}
			}
		}
	}
	if changed {
		if err = s.saveLocked(); err != nil {
			s.loadError = "Could not save recovered task state. Tasks are paused."
		}
	}
	return s
}
func (s *taskStore) saveLocked() error {
	if s.loadError != "" {
		return errors.New(s.loadError)
	}
	return atomicJSON(s.path, struct {
		Tasks []task    `json:"tasks"`
		Runs  []taskRun `json:"runs"`
	}{s.Tasks, s.Runs})
}
func (s *taskStore) snapshot() map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()
	return map[string]any{"tasks": append([]task{}, s.Tasks...), "runs": append([]taskRun{}, s.Runs...), "error": s.loadError, "runsWhileOpen": true, "maxConcurrent": 1}
}
func (a *app) listTasks(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, a.tasks.snapshot())
}

func validateTask(t *task, now time.Time) error {
	t.Name = strings.TrimSpace(t.Name)
	t.Prompt = strings.TrimSpace(t.Prompt)
	if t.Name == "" || len(t.Name) > 100 || t.Prompt == "" || len(t.Prompt) > 15000 || len(t.Context) > 48000 {
		return errors.New("Provide a name, instructions, and project context within the displayed limits.")
	}
	if t.Mode == "" {
		t.Mode = "assistant"
	}
	if _, ok := modes[t.Mode]; !ok {
		return errors.New("Choose a valid assistant mode.")
	}
	if !validTextModel(t.Model) {
		return errors.New("Choose a valid text model.")
	}
	if t.MaxRuns < 1 || t.MaxRuns > 100 {
		return errors.New("Set a run limit between 1 and 100.")
	}
	switch t.Schedule {
	case "manual":
		t.Enabled = false
		t.NextRun = time.Time{}
	case "once":
		if t.Enabled && !t.NextRun.After(now) {
			return errors.New("Choose a future run time.")
		}
	case "interval":
		if t.IntervalMinutes < 60 || t.IntervalMinutes > 10080 {
			return errors.New("Recurring tasks can run every hour to every week.")
		}
		if t.Enabled && t.NextRun.IsZero() {
			t.NextRun = now.Add(time.Duration(t.IntervalMinutes) * time.Minute)
		}
	default:
		return errors.New("Choose manual, once, or recurring.")
	}
	if t.Enabled && t.RunCount >= t.MaxRuns {
		return errors.New("This task has reached its run limit. Increase the limit before resuming.")
	}
	return nil
}
func (a *app) createTask(w http.ResponseWriter, r *http.Request) {
	var t task
	if !parseBody(w, r, &t) {
		return
	}
	t.ID = token()[:24]
	t.Created = time.Now()
	t.RunCount = 0
	if err := validateTask(&t, time.Now()); err != nil {
		writeJSON(w, 400, map[string]string{"error": err.Error()})
		return
	}
	s := a.tasks
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.Tasks) >= 30 {
		writeJSON(w, 409, map[string]string{"error": "Task limit reached. Delete an unused task first."})
		return
	}
	s.Tasks = append(s.Tasks, t)
	if err := s.saveLocked(); err != nil {
		s.Tasks = s.Tasks[:len(s.Tasks)-1]
		writeJSON(w, 500, map[string]string{"error": "Could not save task: " + err.Error()})
		return
	}
	writeJSON(w, 201, t)
}
func (a *app) editTask(w http.ResponseWriter, r *http.Request) {
	var t task
	if !parseBody(w, r, &t) {
		return
	}
	s := a.tasks
	s.mu.Lock()
	defer s.mu.Unlock()
	for i, old := range s.Tasks {
		if old.ID == r.PathValue("id") {
			t.ID = old.ID
			t.Created = old.Created
			t.RunCount = old.RunCount
			if err := validateTask(&t, time.Now()); err != nil {
				writeJSON(w, 400, map[string]string{"error": err.Error()})
				return
			}
			s.Tasks[i] = t
			if err := s.saveLocked(); err != nil {
				s.Tasks[i] = old
				writeJSON(w, 500, map[string]string{"error": "Could not save task."})
				return
			}
			writeJSON(w, 200, t)
			return
		}
	}
	writeJSON(w, 404, map[string]string{"error": "Task not found."})
}
func (a *app) deleteTask(w http.ResponseWriter, r *http.Request) {
	s := a.tasks
	s.mu.Lock()
	defer s.mu.Unlock()
	id := r.PathValue("id")
	if _, busy := s.cancel[id]; busy {
		writeJSON(w, 409, map[string]string{"error": "Stop the running task before deleting it."})
		return
	}
	for i, t := range s.Tasks {
		if t.ID == id {
			old := append([]task{}, s.Tasks...)
			s.Tasks = append(s.Tasks[:i], s.Tasks[i+1:]...)
			if err := s.saveLocked(); err != nil {
				s.Tasks = old
				writeJSON(w, 500, map[string]string{"error": "Could not delete task."})
				return
			}
			writeJSON(w, 200, map[string]bool{"deleted": true})
			return
		}
	}
	writeJSON(w, 404, map[string]string{"error": "Task not found."})
}
func (a *app) runTask(w http.ResponseWriter, r *http.Request) {
	run, err := a.beginTask(r.PathValue("id"), false)
	if err != nil {
		writeJSON(w, 409, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, 202, run)
}
func (a *app) cancelTask(w http.ResponseWriter, r *http.Request) {
	s := a.tasks
	s.mu.Lock()
	defer s.mu.Unlock()
	cancel, ok := s.cancel[r.PathValue("id")]
	if !ok {
		writeJSON(w, 409, map[string]string{"error": "This task is not running."})
		return
	}
	cancel()
	writeJSON(w, 200, map[string]bool{"stopping": true})
}

func (a *app) beginTask(id string, scheduled bool) (taskRun, error) {
	a.mu.RLock()
	key := a.apiKey
	a.mu.RUnlock()
	if key == "" {
		return taskRun{}, errors.New("Connect OpenAI in Settings before running tasks.")
	}
	s := a.tasks
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.loadError != "" {
		return taskRun{}, errors.New(s.loadError)
	}
	if len(s.cancel) > 0 {
		return taskRun{}, errors.New("Another AI task is running. Wait or stop it first.")
	}
	index := -1
	for i, t := range s.Tasks {
		if t.ID == id {
			index = i
			break
		}
	}
	if index < 0 {
		return taskRun{}, errors.New("Task not found.")
	}
	old := s.Tasks[index]
	t := old
	now := time.Now()
	if t.RunCount >= t.MaxRuns {
		return taskRun{}, errors.New("This task has reached its run limit.")
	}
	if scheduled && (!t.Enabled || t.NextRun.IsZero() || t.NextRun.After(now)) {
		return taskRun{}, errors.New("Task is not due.")
	}
	run := taskRun{ID: token()[:24], TaskID: t.ID, Name: t.Name, Model: t.Model, Status: "running", Started: now}
	t.RunCount++
	if scheduled {
		if t.Schedule == "once" {
			t.Enabled = false
		} else {
			t.NextRun = now.Add(time.Duration(t.IntervalMinutes) * time.Minute)
		}
	}
	if t.RunCount >= t.MaxRuns {
		t.Enabled = false
	}
	oldRuns := append([]taskRun{}, s.Runs...)
	s.Tasks[index] = t
	s.Runs = append([]taskRun{run}, s.Runs...)
	if len(s.Runs) > 150 {
		s.Runs = s.Runs[:150]
	}
	// Write the claim before calling OpenAI to avoid duplicate calls after restart.
	if err := s.saveLocked(); err != nil {
		s.Tasks[index] = old
		s.Runs = oldRuns
		return taskRun{}, fmt.Errorf("Could not record task run: %w", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
	s.cancel[t.ID] = cancel
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		defer cancel()
		result, err := a.complete(ctx, chatInput{Messages: []message{{Role: "user", Content: t.Prompt}}, Mode: t.Mode, Context: t.Context, Model: t.Model})
		s.mu.Lock()
		defer s.mu.Unlock()
		delete(s.cancel, t.ID)
		for i := range s.Runs {
			if s.Runs[i].ID == run.ID {
				s.Runs[i].Finished = time.Now()
				s.Runs[i].Result = result
				s.Runs[i].Status = "completed"
				if err != nil {
					s.Runs[i].Status = "failed"
					s.Runs[i].Error = err.Error()
					if errors.Is(err, context.Canceled) {
						s.Runs[i].Status = "cancelled"
					}
				}
			}
		}
		// Pause recurring tasks on errors instead of repeatedly spending API credit.
		if err != nil {
			for i := range s.Tasks {
				if s.Tasks[i].ID == t.ID {
					s.Tasks[i].Enabled = false
				}
			}
		}
		if err := s.saveLocked(); err != nil {
			s.loadError = "Could not save task results. Tasks are paused; keep VYRA open and export the visible result."
		}
	}()
	return run, nil
}
func (a *app) startTasks() {
	ctx, cancel := context.WithCancel(context.Background())
	a.tasks.mu.Lock()
	a.tasks.stop = cancel
	a.tasks.mu.Unlock()
	a.tasks.wg.Add(1)
	go func() {
		defer a.tasks.wg.Done()
		ticker := time.NewTicker(15 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				a.tasks.mu.Lock()
				id := ""
				if a.tasks.loadError == "" {
					for _, t := range a.tasks.Tasks {
						if t.Enabled && !t.NextRun.IsZero() && !t.NextRun.After(time.Now()) && t.RunCount < t.MaxRuns {
							id = t.ID
							break
						}
					}
				}
				a.tasks.mu.Unlock()
				if id != "" {
					_, _ = a.beginTask(id, true)
				}
			}
		}
	}()
}
func (a *app) stopTasks() {
	s := a.tasks
	s.mu.Lock()
	if s.stop != nil {
		s.stop()
	}
	for _, cancel := range s.cancel {
		cancel()
	}
	s.mu.Unlock()
	s.wg.Wait()
}
