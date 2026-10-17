package main

import (
	"encoding/json"
	"errors"
	"time"
)

// Merge project changes by modification time so a cached webview cannot erase
// an Intelligence/background-task edit. Explicit deletions carry tombstones.
func mergeProjects(saved []byte, incoming []json.RawMessage, deleted map[string]string) ([]json.RawMessage, map[string]string, error) {
	var old struct {
		Projects []json.RawMessage `json:"projects"`
		Deleted  map[string]string `json:"deletedProjects"`
	}
	if len(saved) > 0 && json.Unmarshal(saved, &old) != nil {
		return nil, nil, errors.New("Saved workspace could not be read. The original file is preserved.")
	}
	tombstones := map[string]string{}
	for id, when := range old.Deleted {
		tombstones[id] = when
	}
	parseTime := func(s string) time.Time { t, _ := time.Parse(time.RFC3339, s); return t }
	for id, when := range deleted {
		if len(id) <= 100 && parseTime(when).After(parseTime(tombstones[id])) {
			tombstones[id] = when
		}
	}
	type entry struct {
		raw      json.RawMessage
		modified time.Time
	}
	byID := map[string]entry{}
	order := []string{}
	for _, list := range [][]json.RawMessage{old.Projects, incoming} {
		for _, raw := range list {
			var project struct {
				ID      string `json:"id"`
				Updated string `json:"updated"`
				Created string `json:"created"`
			}
			if json.Unmarshal(raw, &project) != nil || project.ID == "" || len(project.ID) > 100 {
				return nil, nil, errors.New("Invalid project record.")
			}
			modified := parseTime(project.Updated)
			if modified.IsZero() {
				modified = parseTime(project.Created)
			}
			previous, exists := byID[project.ID]
			if !exists {
				order = append(order, project.ID)
			}
			if !exists || !modified.Before(previous.modified) {
				byID[project.ID] = entry{raw, modified}
			}
		}
	}
	result := []json.RawMessage{}
	for _, id := range order {
		project := byID[id]
		deletedAt := parseTime(tombstones[id])
		if !deletedAt.IsZero() && !deletedAt.Before(project.modified) {
			continue
		}
		result = append(result, project.raw)
	}
	if len(result) > 100 {
		return nil, nil, errors.New("Project limit reached.")
	}
	return result, tombstones, nil
}
