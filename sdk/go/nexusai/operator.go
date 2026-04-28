package nexusai

import (
	"fmt"
	"math"
	"math/rand"
	"net/http"
	"os"
	"strings"
	"time"
)

// SDKVersion is the current Go SDK version.
const SDKVersion = "0.2.0"

// APIVersion is the Nexus AI API version this SDK targets.
const APIVersion = "v1"

// RetryConfig controls exponential-backoff retry behaviour.
type RetryConfig struct {
	MaxAttempts    int
	BaseDelayMs    float64
	MaxDelayMs     float64
	Jitter         float64
	RetryableHTTP  map[int]bool
}

// DefaultRetryConfig returns sensible production retry defaults.
func DefaultRetryConfig() RetryConfig {
	return RetryConfig{
		MaxAttempts: 3,
		BaseDelayMs: 500,
		MaxDelayMs:  30_000,
		Jitter:      0.1,
		RetryableHTTP: map[int]bool{
			http.StatusTooManyRequests:     true,
			http.StatusInternalServerError: true,
			http.StatusBadGateway:          true,
			http.StatusServiceUnavailable:  true,
			http.StatusGatewayTimeout:      true,
		},
	}
}

func (r RetryConfig) delay(attempt int) time.Duration {
	raw := r.BaseDelayMs * math.Pow(2, float64(attempt))
	capped := math.Min(raw, r.MaxDelayMs)
	jitterAmt := capped * r.Jitter * (2*rand.Float64() - 1)
	ms := math.Max(0, capped+jitterAmt)
	return time.Duration(ms) * time.Millisecond
}

// OperatorConfig configures a NexusOperator.
type OperatorConfig struct {
	BaseURL         string
	APIKey          string
	TimeoutSeconds  float64
	VerifyHealth    bool
	Retry           RetryConfig
	DefaultModel    string
	DefaultProvider string
}

// DefaultOperatorConfig returns env-var-sourced config with production defaults.
func DefaultOperatorConfig() OperatorConfig {
	baseURL := os.Getenv("NEXUS_BASE_URL")
	if baseURL == "" {
		baseURL = "http://localhost:8000"
	}
	return OperatorConfig{
		BaseURL:         baseURL,
		APIKey:          os.Getenv("NEXUS_API_KEY"),
		TimeoutSeconds:  60,
		VerifyHealth:    false,
		Retry:           DefaultRetryConfig(),
		DefaultModel:    os.Getenv("NEXUS_DEFAULT_MODEL"),
		DefaultProvider: os.Getenv("NEXUS_DEFAULT_PROVIDER"),
	}
}

// Operator wraps Client with retry, defaults, and health verification.
type Operator struct {
	config OperatorConfig
	client *Client
}

// NexusOperator is kept as a public alias for documentation and compatibility.
type NexusOperator = Operator

// NewOperator creates a new Operator with the given config.
func NewOperator(cfg OperatorConfig) *Operator {
	c := NewClient(cfg.BaseURL, cfg.APIKey)
	c.HTTP.Timeout = time.Duration(cfg.TimeoutSeconds * float64(time.Second))
	return &Operator{config: cfg, client: c}
}

// DefaultOperator creates an Operator from DefaultOperatorConfig (env vars).
func DefaultOperator() *Operator {
	return NewOperator(DefaultOperatorConfig())
}

// Client returns the underlying Client for direct access.
func (o *Operator) Client() *Client { return o.client }

// withRetry executes fn with exponential-backoff retry.
func (o *Operator) withRetry(fn func() (map[string]any, error)) (map[string]any, error) {
	var lastErr error
	for attempt := 0; attempt < o.config.Retry.MaxAttempts; attempt++ {
		result, err := fn()
		if err == nil {
			return result, nil
		}
		lastErr = err
		// Check if this is a retryable HTTP status by parsing the error string.
		if !o.isRetryable(err) || attempt == o.config.Retry.MaxAttempts-1 {
			break
		}
		time.Sleep(o.config.Retry.delay(attempt))
	}
	return nil, lastErr
}

func (o *Operator) isRetryable(err error) bool {
	if err == nil {
		return false
	}
	msg := err.Error()
	for status := range o.config.Retry.RetryableHTTP {
		if strings.Contains(msg, fmt.Sprintf("%d", status)) {
			return true
		}
	}
	// Network errors (connection refused, timeout) are retryable.
	return strings.Contains(msg, "connection refused") ||
		strings.Contains(msg, "timeout") ||
		strings.Contains(msg, "EOF")
}

// ── Health ────────────────────────────────────────────────────────────────────

// Health calls /health with retry.
func (o *Operator) Health() (map[string]any, error) {
	return o.withRetry(func() (map[string]any, error) {
		out := map[string]any{}
		return out, o.client.do(http.MethodGet, "/health", nil, &out)
	})
}

// IsHealthy returns true if the server responds with a healthy status.
func (o *Operator) IsHealthy() bool {
	h, err := o.Health()
	if err != nil {
		return false
	}
	status, _ := h["status"].(string)
	status = strings.ToLower(status)
	return status == "ok" || status == "healthy" || status == "ready"
}

// ── Chat ──────────────────────────────────────────────────────────────────────

// Chat sends a chat completion request with retry.
func (o *Operator) Chat(messages []map[string]any, model string, stream bool) (map[string]any, error) {
	if model == "" {
		model = o.config.DefaultModel
	}
	return o.withRetry(func() (map[string]any, error) {
		return o.client.ChatCompletions(model, messages, stream)
	})
}

// ── Agent ─────────────────────────────────────────────────────────────────────

// RunAgent executes an agent task with retry.
func (o *Operator) RunAgent(task, sessionID string, history []map[string]any) (map[string]any, error) {
	return o.withRetry(func() (map[string]any, error) {
		return o.client.RunAgent(task, sessionID, history)
	})
}

// ── Dataset benchmarks ────────────────────────────────────────────────────────

// BenchmarkDataset runs a publishable dataset benchmark (gsm8k, truthfulqa, humaneval, mmlu, hellaswag).
func (o *Operator) BenchmarkDataset(dataset, provider, model string, maxSamples int) (map[string]any, error) {
	if provider == "" {
		provider = o.config.DefaultProvider
	}
	if model == "" {
		model = o.config.DefaultModel
	}
	if maxSamples <= 0 {
		maxSamples = 10
	}
	return o.withRetry(func() (map[string]any, error) {
		out := map[string]any{}
		return out, o.client.do(http.MethodPost, "/benchmark/dataset/run", map[string]any{
			"dataset":     dataset,
			"provider":    provider,
			"model":       model,
			"max_samples": maxSamples,
		}, &out)
	})
}

// BenchmarkDatasetSuite runs all (or selected) dataset benchmarks.
func (o *Operator) BenchmarkDatasetSuite(datasets []string, provider, model string, maxSamplesPerDataset int) (map[string]any, error) {
	if provider == "" {
		provider = o.config.DefaultProvider
	}
	if model == "" {
		model = o.config.DefaultModel
	}
	if maxSamplesPerDataset <= 0 {
		maxSamplesPerDataset = 10
	}
	return o.withRetry(func() (map[string]any, error) {
		out := map[string]any{}
		return out, o.client.do(http.MethodPost, "/benchmark/dataset/suite", map[string]any{
			"datasets":                datasets,
			"provider":                provider,
			"model":                   model,
			"max_samples_per_dataset": maxSamplesPerDataset,
		}, &out)
	})
}

// BenchmarkExport retrieves benchmark artifacts for a run ID.
func (o *Operator) BenchmarkExport(runID string, formats []string) (map[string]any, error) {
	path := "/benchmark/export/" + runID
	if len(formats) > 0 {
		path += "?formats=" + strings.Join(formats, ",")
	}
	return o.withRetry(func() (map[string]any, error) {
		out := map[string]any{}
		return out, o.client.do(http.MethodGet, path, nil, &out)
	})
}

// ── Compatibility ─────────────────────────────────────────────────────────────

// CompatibilityReport summarises SDK and server compatibility.
type CompatibilityReport struct {
	SDKVersion      string `json:"sdk_version"`
	GoVersion       string `json:"go_version"`
	ServerReachable bool   `json:"server_reachable"`
	ServerVersion   string `json:"server_version"`
	APIVersion      string `json:"api_version"`
}

// CheckCompatibility probes the server and returns a compatibility report.
func (o *Operator) CheckCompatibility() CompatibilityReport {
	report := CompatibilityReport{
		SDKVersion: SDKVersion,
		APIVersion: APIVersion,
	}

	h, err := o.Health()
	if err == nil {
		report.ServerReachable = true
		report.ServerVersion, _ = h["version"].(string)
		report.APIVersion, _ = h["api_version"].(string)
		if report.APIVersion == "" {
			report.APIVersion = APIVersion
		}
	}

	return report
}
