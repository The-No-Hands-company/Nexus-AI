package nexusai

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

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

func (c *Client) ChatCompletions(model string, messages []map[string]any, stream bool) (map[string]any, error) {
	payload := map[string]any{"model": model, "messages": messages, "stream": stream}
	out := map[string]any{}
	err := c.do(http.MethodPost, "/v1/chat/completions", payload, &out)
	return out, err
}

func (c *Client) RunAgent(task, sessionID string, history []map[string]any) (map[string]any, error) {
	payload := map[string]any{"task": task, "session_id": sessionID, "history": history}
	out := map[string]any{}
	err := c.do(http.MethodPost, "/v1/agent", payload, &out)
	return out, err
}

func (c *Client) AutonomyPlan(goal string, maxSubtasks int) (map[string]any, error) {
	payload := map[string]any{"goal": goal, "max_subtasks": maxSubtasks}
	out := map[string]any{}
	err := c.do(http.MethodPost, "/v1/autonomy/plan", payload, &out)
	return out, err
}

func (c *Client) BenchmarkDataset(dataset, provider, model string, maxSamples int) (map[string]any, error) {
	payload := map[string]any{
		"dataset":     dataset,
		"provider":    provider,
		"model":       model,
		"max_samples": maxSamples,
	}
	out := map[string]any{}
	err := c.do(http.MethodPost, "/benchmark/dataset/run", payload, &out)
	return out, err
}

func (c *Client) BenchmarkDatasetSuite(datasets []string, provider, model string, maxSamplesPerDataset int) (map[string]any, error) {
	payload := map[string]any{
		"datasets":                datasets,
		"provider":                provider,
		"model":                   model,
		"max_samples_per_dataset": maxSamplesPerDataset,
	}
	out := map[string]any{}
	err := c.do(http.MethodPost, "/benchmark/dataset/suite", payload, &out)
	return out, err
}

func (c *Client) BenchmarkExport(runID string, formats []string) (map[string]any, error) {
	path := "/benchmark/export/" + runID
	if len(formats) > 0 {
		path += "?formats=" + strings.Join(formats, ",")
	}
	out := map[string]any{}
	err := c.do(http.MethodGet, path, nil, &out)
	return out, err
}

func (c *Client) BenchmarkDatasetHistory(dataset string, limit int) (map[string]any, error) {
	path := fmt.Sprintf("/benchmark/dataset/history/%s?limit=%d", dataset, limit)
	out := map[string]any{}
	err := c.do(http.MethodGet, path, nil, &out)
	return out, err
}
