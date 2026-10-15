package main

import (
	"errors"
	"net"
	"net/http"
	"net/url"
	"strings"
)

func externalURL(raw string) (string, error) {
	if len(raw) > 16384 || strings.ContainsAny(raw, "\x00\r\n") {
		return "", errors.New("Invalid link.")
	}
	u, e := url.Parse(raw)
	if e != nil || (u.Scheme != "https" && u.Scheme != "http") || u.User != nil || u.Hostname() == "" {
		return "", errors.New("Only web links can open outside VYRA.")
	}
	host := strings.ToLower(u.Hostname())
	ip := net.ParseIP(host)
	if host == "localhost" || strings.HasSuffix(host, ".localhost") || (ip != nil && (ip.IsLoopback() || ip.IsPrivate() || ip.IsUnspecified() || ip.IsLinkLocalUnicast())) {
		return "", errors.New("Local application links stay inside VYRA.")
	}
	return u.String(), nil
}
func (a *app) openLink(w http.ResponseWriter, r *http.Request) {
	var b struct {
		URL string `json:"url"`
	}
	if !parseBody(w, r, &b) {
		return
	}
	target, err := externalURL(b.URL)
	if err != nil {
		writeJSON(w, 400, map[string]string{"error": err.Error()})
		return
	}
	if err = openExternal(target); err != nil {
		writeJSON(w, 503, map[string]string{"error": "Could not open the link in your browser."})
		return
	}
	writeJSON(w, 200, map[string]bool{"opened": true})
}
