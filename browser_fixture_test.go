package main

// This test-only fixture serves the real application with a fake provider.
// It is excluded from release binaries and never uses real credentials.
import (
	"encoding/json"
	"net"
	"net/http"
	"os"
	"strings"
	"testing"
)

func TestBrowserFixture(t *testing.T) {
	if os.Getenv("VYRA_BROWSER_TEST") != "1" {
		t.Skip("Opt-in browser fixture")
	}
	a := testApp(t)
	a.client.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		switch {
		case strings.Contains(r.URL.Path, "/models"):
			return fakeResponse(200, `{"data":[{"id":"gpt-6-astra"},{"id":"gpt-5-mini"}]}`), nil
		case strings.Contains(r.URL.Path, "/transcriptions"):
			return fakeResponse(200, `{"text":"Hello VYRA, study my project."}`), nil
		default:
			var body struct {
				Stream bool `json:"stream"`
			}
			json.NewDecoder(r.Body).Decode(&body)
			if body.Stream {
				return fakeResponse(200, "data: {\"type\":\"response.output_text.delta\",\"delta\":\"I studied your project. Here is a concrete improvement.\\n\\n```go\\nfmt.Println(\\\"VYRA\\\")\\n```\"}\n\ndata: {\"type\":\"response.completed\"}\n\n"), nil
			}
			return fakeResponse(200, `{"status":"completed","output":[{"content":[{"type":"output_text","text":"Project review complete. Add input validation and verify the result."}]}]}`), nil
		}
	})
	l, err := net.Listen("tcp", "127.0.0.1:48821")
	if err != nil {
		t.Fatal(err)
	}
	a.server = &http.Server{Handler: a.routes()}
	a.startTasks()
	defer a.stopTasks()
	t.Log("VYRA browser fixture ready at http://127.0.0.1:48821")
	a.server.Serve(l)
}
