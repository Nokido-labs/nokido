package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"sync"
	"time"
)

const defaultOllamaURL = "http://127.0.0.1:11434/api/generate"
// ECOUTE CONFINEE A LA BOUCLE LOCALE (audit securite 2026-09-18, finding #10).
//
// La valeur etait ":8779". En Go, un hote VIDE signifie TOUTES les interfaces --
// et la mesure sur la table des sockets vivante le confirmait :
//
//	TCP    0.0.0.0:8779    LISTENING
//	TCP    [::]:8779       LISTENING
//
// IPv4 ET IPv6. Ce service etait le SEUL de la flotte Nokido a ecouter au-dela
// de la boucle locale, alors que les vingt autres y sont confines. Rien dans sa
// declaration de service ne demandait cette exposition : elle venait d'un hote
// omis, pas d'une decision.
//
// L'omission est le piege : ":8779" se relit comme « le port 8779 », et ne dit
// pas « depuis n'importe ou ». On ecrit donc l'hote, pour qu'il soit lu.
const defaultPort = "127.0.0.1:8779"

// ── Request / Response types ─────────────────────────────────────────────────

type SiloRequest struct {
	Name       string `json:"name"`
	Model      string `json:"model"`
	Prompt     string `json:"prompt"`
	OllamaURL  string `json:"ollama_url"`
	TimeoutSec int    `json:"timeout"`
	NumPredict int    `json:"num_predict"`
	Temp       float64 `json:"temperature"`
}

type DispatchRequest struct {
	Silos           []SiloRequest `json:"silos"`
	OllamaURL       string        `json:"ollama_url"`
	ReconcilePrompt string        `json:"reconcile_prompt"`
	ReconcileModel  string        `json:"reconcile_model"`
}

type SiloResult struct {
	Name      string `json:"name"`
	Response  string `json:"response"`
	ElapsedMS int64  `json:"elapsed_ms"`
	Error     string `json:"error,omitempty"`
}

type DispatchResponse struct {
	Results    []SiloResult `json:"results"`
	Reconciled string       `json:"reconciled,omitempty"`
	TotalMS    int64        `json:"total_ms"`
}

// ── Ollama wire types ─────────────────────────────────────────────────────────

type ollamaReq struct {
	Model   string         `json:"model"`
	Prompt  string         `json:"prompt"`
	Stream  bool           `json:"stream"`
	Options map[string]any `json:"options"`
}

type ollamaResp struct {
	Response string `json:"response"`
}

// ── Core call ─────────────────────────────────────────────────────────────────

func callOllama(url, model, prompt string, timeoutSec, numPredict int, temp float64) (string, error) {
	if numPredict <= 0 {
		numPredict = 500
	}
	if temp <= 0 {
		temp = 0.1
	}
	payload := ollamaReq{
		Model:  model,
		Prompt: prompt,
		Stream: false,
		Options: map[string]any{
			"temperature": temp,
			"num_predict": numPredict,
		},
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	client := &http.Client{Timeout: time.Duration(timeoutSec) * time.Second}
	resp, err := client.Post(url, "application/json", bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	var or ollamaResp
	if err := json.Unmarshal(data, &or); err != nil {
		return "", fmt.Errorf("decode: %w (body=%s)", err, string(data[:min(200, len(data))]))
	}
	return or.Response, nil
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// ── HTTP handler ──────────────────────────────────────────────────────────────

func handleDispatch(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST only", http.StatusMethodNotAllowed)
		return
	}
	var req DispatchRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	baseURL := req.OllamaURL
	if baseURL == "" {
		baseURL = defaultOllamaURL
	}

	start := time.Now()
	results := make([]SiloResult, len(req.Silos))
	var wg sync.WaitGroup

	for i, silo := range req.Silos {
		wg.Add(1)
		go func(idx int, s SiloRequest) {
			defer wg.Done()
			t0 := time.Now()
			url := s.OllamaURL
			if url == "" {
				url = baseURL
			}
			timeout := s.TimeoutSec
			if timeout <= 0 {
				timeout = 30
			}
			resp, err := callOllama(url, s.Model, s.Prompt, timeout, s.NumPredict, s.Temp)
			elapsed := time.Since(t0).Milliseconds()
			if err != nil {
				results[idx] = SiloResult{Name: s.Name, ElapsedMS: elapsed, Error: err.Error()}
			} else {
				results[idx] = SiloResult{Name: s.Name, Response: resp, ElapsedMS: elapsed}
			}
		}(i, silo)
	}
	wg.Wait()

	var reconciled string
	if req.ReconcilePrompt != "" && req.ReconcileModel != "" {
		reconciled, _ = callOllama(baseURL, req.ReconcileModel, req.ReconcilePrompt, 90, 1000, 0.1)
	}

	out := DispatchResponse{
		Results:    results,
		Reconciled: reconciled,
		TotalMS:    time.Since(start).Milliseconds(),
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(out)
}

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/dispatch", handleDispatch)
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprintln(w, `{"ok":true,"service":"forge-dispatcher"}`)
	})

	log.Printf("[forge-dispatcher] listening on %s (goroutine-per-silo, no GIL)", defaultPort)
	if err := http.ListenAndServe(defaultPort, mux); err != nil {
		log.Fatal(err)
	}
}
