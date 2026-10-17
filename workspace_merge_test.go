package main

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestStaleWorkspaceCannotEraseIntelligenceProjectChanges(t *testing.T) {
	saved := []byte(`{"projects":[{"id":"one","name":"Strategy","note":"New measured findings","updated":"2026-10-16T12:00:00Z"},{"id":"new","name":"Created by task","updated":"2026-10-16T12:00:00Z"}]}`)
	stale := []json.RawMessage{json.RawMessage(`{"id":"one","name":"Strategy","note":"Old findings","created":"2026-10-15T12:00:00Z"}`)}
	projects, _, err := mergeProjects(saved, stale, nil)
	raw, _ := json.Marshal(projects)
	if err != nil || len(projects) != 2 || !strings.Contains(string(raw), "New measured findings") || !strings.Contains(string(raw), "Created by task") {
		t.Fatal(string(raw), err)
	}
	deleted := map[string]string{"one": "2026-10-16T13:00:00Z"}
	projects, tombstones, err := mergeProjects(saved, stale, deleted)
	if err != nil || len(projects) != 1 {
		t.Fatal(projects, err)
	}
	persisted, _ := json.Marshal(map[string]any{"projects": projects, "deletedProjects": tombstones})
	projects, _, err = mergeProjects(persisted, stale, nil)
	if err != nil || len(projects) != 1 {
		t.Fatal("Stale window resurrected deleted project", err)
	}
}
