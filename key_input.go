package main

import (
	"errors"
	"strings"
	"unicode"
)

// Accept normal copy/paste wrappers without guessing or exposing a secret.
// OpenAI determines whether a complete credential is active and authorized.
func normalizeAPIKey(input string) (string, error) {
	raw := strings.TrimSpace(input)
	if raw == "" {
		return "", nil
	}
	value := strings.Map(func(r rune) rune {
		switch r {
		case '\u200b', '\u200c', '\u200d', '\ufeff', '\u2060':
			return -1
		}
		return r
	}, raw)
	value = strings.TrimSpace(value)
	for i := 0; i < 4; i++ {
		before := value
		if len(value) > 7 && strings.EqualFold(value[:7], "Bearer ") {
			value = strings.TrimSpace(value[7:])
		}
		value = strings.TrimPrefix(value, "export ")
		if strings.HasPrefix(value, "OPENAI_API_KEY=") {
			value = strings.TrimSpace(strings.TrimPrefix(value, "OPENAI_API_KEY="))
		}
		for _, pair := range [][2]string{{"\"", "\""}, {"'", "'"}, {"`", "`"}, {"“", "”"}, {"‘", "’"}} {
			if strings.HasPrefix(value, pair[0]) && strings.HasSuffix(value, pair[1]) && len(value) >= len(pair[0])+len(pair[1]) {
				value = strings.TrimSpace(value[len(pair[0]) : len(value)-len(pair[1])])
				break
			}
		}
		if value == before {
			break
		}
	}
	if strings.Contains(value, "...") || strings.ContainsAny(value, "…*•") {
		return "", errors.New("This is a shortened or hidden key. Copy the complete secret key from OpenAI when it is created; the masked key in the key list cannot connect VYRA.")
	}
	if !strings.HasPrefix(value, "sk-") || len(value) < 20 || len(value) > 8192 || strings.ContainsFunc(value, unicode.IsSpace) || strings.ContainsRune(value, '\x00') {
		return "", errors.New("Paste the complete OpenAI secret key, starting with sk-. Use the secret value from OpenAI’s API keys page, rather than its name, ID or a shortened preview.")
	}
	return value, nil
}
