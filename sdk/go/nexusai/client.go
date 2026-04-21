package nexusai

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// ── Types ─────────────────────────────────────────────────────────────────────

type ChatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type StreamChunk struct {
	Delta        string         `json:"delta"`
	FinishReason string         `json:"finish_reason,omitempty"`
	Raw          map[string]any `json:"raw,omitempty"`
}

type AgentTrace struct {
	TraceID string           `json:"trace_id"`
	Steps   []map[string]any `json:"steps"`
	Status  string           `json:"status"`
	Raw     map[string]any   `json:"raw,omitempty"`
}

type AgentListing struct {
	AgentID      string         `json:"agent_id"`
	Name         string         `json:"name"`
	Description  string         `json:"description"`
	Capabilities []string       `json:"capabilities"`
	Raw          map[string]any `json:"raw,omitempty"`
}

// ── Client ────────────────────────────────────────────────────────────────────

type Client struct {
	BaseURL string
	APIKey  string
	HTTP    *http.Client
}

func NewClient(baseURL, apiKey string) *Client {
	return &Client{
		BaseURL: strings.TrimRight(baseURL, "/"),
		APIKey:  apiKey,
		HTTP:    &http.Client{Timeout: 30 * time.Second},
	}
}

func (c *Client) do(method, path string, body any, out any) error {
	var reader io.Reader
	if body != nil {
		payload, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewBuffer(payload)
	}
	req, err := http.NewRequest(method, c.BaseURL+path, reader)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.APIKey)
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		raw, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("%s %s failed: %d %s", method, path, resp.StatusCode, string(raw))
	}
	if out == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

// streamSSE calls path with payload and calls onChunk for every parsed SSE line.
// Caller provides a context to cancel mid-stream.
func (c *Client) streamSSE(ctx context.Context, path string, payload any, onChunk func(StreamChunk) error) error {
	data, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.BaseURL+path, bytes.NewBuffer(data))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.APIKey)
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		raw, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("POST %s failed: %d %s", path, resp.StatusCode, string(raw))
	}

	scanner := bufio.NewScanner(resp.Body)
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(line, "data: ") {
			continue
		}
		dataStr := strings.TrimSpace(line[6:])
		if dataStr == "[DONE]" {
			break
		}
		var obj map[string]any
		if err := json.Unmarshal([]byte(dataStr), &obj); err != nil {
			continue
		}
		chunk := StreamChunk{Raw: obj}
		if choices, ok := obj["choices"].([]any); ok && len(choices) > 0 {
			if choice, ok := choices[0].(map[string]any); ok {
				if delta, ok := choice["delta"].(map[string]any); ok {
					chunk.Delta, _ = delta["content"].(string)
				}
				chunk.FinishReason, _ = choice["finish_reason"].(string)
			}
		} else {
			chunk.Delta, _ = obj["content"].(string)
			chunk.FinishReason, _ = obj["finish_reason"].(string)
		}
		if err := onChunk(chunk); err != nil {
			return err
		}
	}
	return scanner.Err()
}

// ── Chat ──────────────────────────────────────────────────────────────────────

func (c *Client) ChatCompletions(model string, messages []map[string]any, stream bool) (map[string]any, error) {
	payload := map[string]any{"model": model, "messages": messages, "stream": stream}
	out := map[string]any{}
	return out, c.do(http.MethodPost, "/v1/chat/completions", payload, &out)
}

func (c *Client) ChatStream(ctx context.Context, model string, messages []map[string]any, onChunk func(StreamChunk) error) error {
	return c.streamSSE(ctx, "/v1/chat/completions",
		map[string]any{"model": model, "messages": messages, "stream": true}, onChunk)
}

// ── Agent ─────────────────────────────────────────────────────────────────────

func (c *Client) RunAgent(task, sessionID string, history []map[string]any) (map[string]any, error) {
	payload := map[string]any{"task": task, "session_id": sessionID, "history": history}
	out := map[string]any{}
	return out, c.do(http.MethodPost, "/v1/agent", payload, &out)
}

func (c *Client) StreamAgent(ctx context.Context, task, sessionID string, history []map[string]any, onChunk func(StreamChunk) error) error {
	return c.streamSSE(ctx, "/agent/stream",
		map[string]any{"task": task, "session_id": sessionID, "history": history}, onChunk)
}

func (c *Client) GetAgentTrace(traceID string) (AgentTrace, error) {
	out := map[string]any{}
	if err := c.do(http.MethodGet, "/agent/trace/"+traceID, nil, &out); err != nil {
		return AgentTrace{}, err
	}
	steps, _ := out["steps"].([]map[string]any)
	status, _ := out["status"].(string)
	return AgentTrace{TraceID: traceID, Steps: steps, Status: status, Raw: out}, nil
}

func (c *Client) StopAgent(streamID string) (map[string]any, error) {
	out := map[string]any{}
	return out, c.do(http.MethodPost, "/agent/stop/"+streamID, nil, &out)
}

// ── Agent marketplace ─────────────────────────────────────────────────────────

func (c *Client) ListAgents() ([]AgentListing, error) {
	out := map[string]any{}
	if err := c.do(http.MethodGet, "/agents", nil, &out); err != nil {
		return nil, err
	}
	var raw []any
	if v, ok := out["agents"]; ok {
		raw, _ = v.([]any)
	} else if v, ok := out["data"]; ok {
		raw, _ = v.([]any)
	}
	result := make([]AgentListing, 0, len(raw))
	for _, item := range raw {
		a, _ := item.(map[string]any)
		listing := AgentListing{Raw: a}
		listing.AgentID, _ = a["id"].(string)
		if listing.AgentID == "" {
			listing.AgentID, _ = a["agent_id"].(string)
		}
		listing.Name, _ = a["name"].(string)
		listing.Description, _ = a["description"].(string)
		if caps, ok := a["capabilities"].([]any); ok {
			for _, cap := range caps {
				if s, ok := cap.(string); ok {
					listing.Capabilities = append(listing.Capabilities, s)
				}
			}
		}
		result = append(result, listing)
	}
	return result, nil
}

func (c *Client) GetAgent(agentID string) (map[string]any, error) {
	out := map[string]any{}
	return out, c.do(http.MethodGet, "/agents/"+agentID, nil, &out)
}

func (c *Client) RunNamedAgent(agentID, task string, extra map[string]any) (map[string]any, error) {
	payload := map[string]any{"task": task}
	for k, v := range extra {
		payload[k] = v
	}
	out := map[string]any{}
	return out, c.do(http.MethodPost, "/agents/"+agentID+"/run", payload, &out)
}

// ── Autonomy ──────────────────────────────────────────────────────────────────

func (c *Client) AutonomyPlan(goal string, maxSubtasks int) (map[string]any, error) {
	payload := map[string]any{"goal": goal, "max_subtasks": maxSubtasks}
	out := map[string]any{}
	return out, c.do(http.MethodPost, "/v1/autonomy/plan", payload, &out)
}

func (c *Client) AutonomyExecute(plan map[string]any, stream bool) (map[string]any, error) {
	payload := make(map[string]any, len(plan)+1)
	for k, v := range plan {
		payload[k] = v
	}
	payload["stream"] = stream
	out := map[string]any{}
	return out, c.do(http.MethodPost, "/autonomy/execute", payload, &out)
}

func (c *Client) GetAutonomyTrace(traceID string) (AgentTrace, error) {
	out := map[string]any{}
	if err := c.do(http.MethodGet, "/autonomy/trace/"+traceID, nil, &out); err != nil {
		return AgentTrace{}, err
	}
	steps, _ := out["steps"].([]map[string]any)
	status, _ := out["status"].(string)
	return AgentTrace{TraceID: traceID, Steps: steps, Status: status, Raw: out}, nil
}

// ── Models ────────────────────────────────────────────────────────────────────

func (c *Client) ListModels() (map[string]any, error) {
	out := map[string]any{}
	return out, c.do(http.MethodGet, "/v1/models", nil, &out)
}

// ── Benchmarks ────────────────────────────────────────────────────────────────

func (c *Client) BenchmarkRun(providers []string) (map[string]any, error) {
	if providers == nil {
		providers = []string{}
	}
	out := map[string]any{}
	return out, c.do(http.MethodPost, "/benchmark/run", map[string]any{"providers": providers}, &out)
}

func (c *Client) BenchmarkRegression() (map[string]any, error) {
	out := map[string]any{}
	return out, c.do(http.MethodGet, "/benchmark/regression", nil, &out)
}

func (c *Client) BenchmarkSetBaseline(baseline map[string]any) (map[string]any, error) {
	out := map[string]any{}
	return out, c.do(http.MethodPost, "/benchmark/regression/baseline", baseline, &out)
}

func (c *Client) BenchmarkHistory(provider, model, taskType string, limit int) (map[string]any, error) {
	path := fmt.Sprintf("/benchmark/history?provider=%s&model=%s&task_type=%s&limit=%d",
		provider, model, taskType, limit)
	out := map[string]any{}
	return out, c.do(http.MethodGet, path, nil, &out)
}

func (c *Client) BenchmarkSafety(testCases []map[string]any) (map[string]any, error) {
	if testCases == nil {
		testCases = []map[string]any{}
	}
	out := map[string]any{}
	return out, c.do(http.MethodPost, "/benchmark/safety", map[string]any{"test_cases": testCases}, &out)
}

func (c *Client) BenchmarkDataset(dataset, provider, model string, maxSamples int) (map[string]any, error) {
	if maxSamples <= 0 {
		maxSamples = 10
	}
	out := map[string]any{}
	return out, c.do(http.MethodPost, "/benchmark/dataset/run", map[string]any{
		"dataset":     dataset,
		"provider":    provider,
		"model":       model,
		"max_samples": maxSamples,
	}, &out)
}

func (c *Client) BenchmarkDatasetSuite(datasets []string, provider, model string, maxSamplesPerDataset int) (map[string]any, error) {
	if maxSamplesPerDataset <= 0 {
		maxSamplesPerDataset = 10
	}
	out := map[string]any{}
	return out, c.do(http.MethodPost, "/benchmark/dataset/suite", map[string]any{
		"datasets":                datasets,
		"provider":                provider,
		"model":                   model,
		"max_samples_per_dataset": maxSamplesPerDataset,
	}, &out)
}

func (c *Client) BenchmarkDatasetHistory(dataset string, limit int) (map[string]any, error) {
	path := fmt.Sprintf("/benchmark/dataset/history?dataset=%s&limit=%d", dataset, limit)
	out := map[string]any{}
	return out, c.do(http.MethodGet, path, nil, &out)
}

func (c *Client) BenchmarkExport(runID string, formats []string) (map[string]any, error) {
	path := "/benchmark/export/" + runID
	if len(formats) > 0 {
		path += "?formats=" + strings.Join(formats, ",")
	}
	out := map[string]any{}
	return out, c.do(http.MethodGet, path, nil, &out)
}

// ── Compliance ────────────────────────────────────────────────────────────────

func (c *Client) GetComplianceConfig() (map[string]any, error) {
	out := map[string]any{}
	return out, c.do(http.MethodGet, "/admin/compliance", nil, &out)
}

func (c *Client) UpdateComplianceConfig(config map[string]any) (map[string]any, error) {
	out := map[string]any{}
	return out, c.do(http.MethodPut, "/admin/compliance", config, &out)
}
