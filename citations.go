package main

import (
	"fmt"
	"net/url"
	"sort"
	"strings"
)

type source struct {
	URL   string `json:"url"`
	Title string `json:"title"`
}
type citationAnnotation struct {
	Type  string `json:"type"`
	URL   string `json:"url"`
	Title string `json:"title"`
	Start int    `json:"start_index"`
	End   int    `json:"end_index"`
}
type responseEnvelope struct {
	Status string `json:"status"`
	Output []struct {
		Content []struct {
			Type        string               `json:"type"`
			Text        string               `json:"text"`
			Refusal     string               `json:"refusal"`
			Annotations []citationAnnotation `json:"annotations"`
		} `json:"content"`
	} `json:"output"`
}

func citationSource(a citationAnnotation) (source, bool) {
	u, err := url.Parse(a.URL)
	if a.Type != "url_citation" || err != nil || (u.Scheme != "https" && u.Scheme != "http") || u.Hostname() == "" || u.User != nil || len(a.URL) > 8192 {
		return source{}, false
	}
	title := strings.TrimSpace(a.Title)
	if title == "" {
		title = u.Hostname()
	}
	if len(title) > 500 {
		title = title[:500]
	}
	return source{URL: u.String(), Title: title}, true
}
func responseContent(r responseEnvelope) (string, []source) {
	sources := []source{}
	seen := map[string]int{}
	parts := []string{}
	for _, o := range r.Output {
		for _, c := range o.Content {
			if c.Type == "refusal" {
				parts = append(parts, c.Refusal)
				continue
			}
			if c.Type != "output_text" {
				continue
			}
			text := []rune(c.Text)
			annotations := append([]citationAnnotation(nil), c.Annotations...)
			for _, a := range annotations {
				if s, ok := citationSource(a); ok {
					if _, exists := seen[s.URL]; !exists {
						sources = append(sources, s)
						seen[s.URL] = len(sources)
					}
				}
			}
			sort.SliceStable(annotations, func(i, j int) bool { return annotations[i].Start > annotations[j].Start })
			boundary := len(text)
			for _, a := range annotations {
				s, ok := citationSource(a)
				if !ok {
					continue
				}
				n := seen[s.URL]
				if a.Start < 0 || a.End <= a.Start || a.End > boundary || a.End > len(text) {
					continue
				}
				linkURL := strings.NewReplacer("(", "%28", ")", "%29").Replace(s.URL)
				replacement := []rune(fmt.Sprintf("[%d](%s)", n, linkURL))
				text = append(append(append([]rune{}, text[:a.Start]...), replacement...), text[a.End:]...)
				boundary = a.Start
			}
			parts = append(parts, string(text))
		}
	}
	return strings.TrimSpace(strings.Join(parts, "\n")), sources
}
func withSources(text string, sources []source) string {
	if len(sources) == 0 {
		return text
	}
	text += "\n\nSources:\n"
	for i, s := range sources {
		text += fmt.Sprintf("%d. [%s](%s)\n", i+1, strings.NewReplacer("[", "(", "]", ")", "\n", " ", "\r", " ").Replace(s.Title), strings.NewReplacer("(", "%28", ")", "%29").Replace(s.URL))
	}
	return strings.TrimSpace(text)
}
