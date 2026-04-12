# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| `main` branch | ✅ Active |
| Tagged releases | ✅ Latest release only |
| Older releases | ❌ Not supported |

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security issues via **GitHub's private security advisory system**:

1. Go to the repository on GitHub.
2. Click **Security** → **Advisories** → **Report a vulnerability**.
3. Fill in the details described below.

We aim to acknowledge all reports **within 48 hours** and provide an initial assessment **within 5 business days**.

### What to include

- A clear description of the vulnerability and its impact.
- Steps to reproduce (proof-of-concept if available).
- The version / commit hash you tested against.
- Whether you believe it is exploitable in default deployments.

### What happens next

1. We confirm receipt and open a private advisory.
2. We reproduce and assess severity (using CVSS v3.1).
3. We develop a fix, tested against the reported PoC.
4. We release a patched version and publish the advisory with credit to the reporter (unless you prefer to remain anonymous).

We do **not** offer a bug bounty program at this time, but we will credit reporters in the advisory and changelog.

---

## Security Model

### What Nexus AI protects

| Asset | Protection |
|---|---|
| API keys (provider credentials) | Stored in env vars only; never logged, never sent to LLM in any context window |
| GitHub tokens (`GH_TOKEN`) | Stripped from all message content before LLM call; token extraction runs on every inbound message |
| User passwords | PBKDF2-HMAC-SHA256 with random salt (bcrypt compatible path available); never stored in plaintext |
| JWT session tokens | HS256-signed; secret set via `JWT_SECRET` env var — **must be set to a strong random value in production** |
| Webhook payloads | Optional HMAC-SHA256 validation via `WEBHOOK_SECRET` |
| Chat history | Query-isolated per `user_id` in multi-user mode |

### Shell execution sandbox

`run_command` executes arbitrary shell commands requested by the agent. Protections:

- **RAM cap:** 256 MB per command
- **CPU time:** 10s hard limit
- **Wall clock:** 60s timeout
- **Path restriction:** `/app` (source tree) is blocked for write, delete, and execution
- **No network egress restriction** — by design, the agent can make outbound HTTP requests (e.g. `curl`). If you need to restrict this, use Docker network policies.

**Important:** `run_command` is powerful. In multi-user deployments, consider whether all users should have access to it — future versions will support per-user tool permissions.

### File system access

`write_file` and `delete_file` are scoped to a per-session working directory. They cannot write outside this directory. Path traversal attempts (`../`) are sanitised at the argument level.

### Prompt injection

Nexus AI processes user-supplied text as LLM input. A malicious user could attempt to inject instructions that override the system prompt. Mitigations in place:

- System prompts are separated from user content in the messages array (never concatenated as strings).
- Tool arguments are validated against expected types before execution.
- Full prompt injection defence (classifier + guards) is planned — see [docs/ROADMAP_FEATURES_V2.md](docs/ROADMAP_FEATURES_V2.md) Sprint B.

### Multi-user deployments

When `MULTI_USER=true`:

- Set `JWT_SECRET` to a cryptographically random value (at least 32 bytes). If not set, a random secret is generated at boot — **this means all sessions are invalidated on restart**.
- Use a TLS-terminating reverse proxy (Caddy, Nginx) in front of Nexus AI. The app itself does not handle TLS.
- Set `SESSION_RATE_LIMIT` to a value appropriate for your user count.
- Per-user quotas (`Per-user rate limits + quotas`) are planned but not yet fully implemented.

### Single-user / local deployments

The default configuration (`MULTI_USER=false`) disables authentication entirely. This is intentional for the common `localhost` use case. Do **not** expose Nexus AI directly to the internet without enabling auth or placing an authentication proxy in front.

---

## Known Limitations

- **No per-user tool ACL yet.** All authenticated users have access to the same tool set, including `run_command`.
- **JWT secret resets on restart** if `JWT_SECRET` is not set — invalidates all sessions.
- **No CSP headers** on the web UI in the current release.
- **Prompt injection defence is partial** — classifier and guard pipeline are planned.

These are tracked in the roadmap and are not considered hidden risks — they are listed here for operational transparency.

---

## Dependency Security

We use standard Python packaging (`requirements.txt`). We recommend running `pip audit` or `safety check` regularly in production deployments.

```bash
pip install pip-audit
pip-audit
```

CI will eventually run `pip-audit` on every PR — tracked in the roadmap.

---

## Acknowledgements

We thank all security researchers who responsibly disclose vulnerabilities. Contributors will be credited in the GitHub Advisory and in [CHANGELOG.md](CHANGELOG.md).
