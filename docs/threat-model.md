# Threat model

## Assets

- The explicit target allowlist and lab boundary.
- Hosted-model API credentials.
- Investigation evidence and audit records.
- Tool-execution integrity.
- The guarantee that unsupported claims are not presented as validated findings.

## Trust boundaries

| Boundary | Untrusted input | Enforcement |
|---|---|---|
| Dashboard → API | Target IDs and debug options | Pydantic schemas; allowlist lookup |
| Model → manager | Hypotheses and requested tests | JSON parse, Pydantic schema, one retry |
| Manager → executor | Tool name, target, path, operation | Policy engine and fixed adapter registry |
| Tool → evidence store | XML/JSON subprocess output | Adapter-specific parsing and normalization |
| Evidence → Critic | Potentially incomplete observation | Independent prompt, contradiction checks, confidence reduction |

## Primary abuse cases

### Target escape

An attacker or compromised model attempts to scan another host. The model contract contains a target ID rather than a URL. The policy engine resolves the URL from the server-side allowlist, checks the configured hostname, and rejects a mismatched ID or scope.

### Arbitrary command execution

A model emits shell syntax or custom flags. The backend never executes model text. It selects a pre-registered adapter and constructs its argument array from server-side target data plus a locally validated path.

### Path-based scope escape

A request tries to inject a full URL or `..` traversal through `path`. Schema validation requires a leading slash and rejects traversal and `://`.

### Confident hallucination

The Investigator declares a vulnerability from a route name or generic reachability. Investigator output is stored as a hypothesis only. The Critic receives normalized evidence and can reject, request evidence, or send the case to a human. A validated database record requires a successful critic decision and a non-degraded run.

### Tool or provider outage

Timeouts, missing binaries, nonzero exits, empty output, provider errors, and invalid JSON become explicit events. They do not crash the API and cannot raise a finding above `NEEDS_HUMAN_REVIEW`.

### Denial of wallet/service

Per-investigation model and tool budgets cap the loop. Tool and model calls have hard timeouts. The MVP is single-process and not production rate-limited; API authentication and distributed rate limiting are required before multi-user deployment.

## Residual risks

- The fake target is intentionally insecure and must never host real data.
- The demo failure endpoint should be disabled outside development.
- PostgreSQL credentials in Compose are local defaults, not deployment secrets.
- Live provider content may contain sensitive evidence; use approved providers and retention settings.
- The MVP does not sandbox each subprocess in a separate ephemeral container. It constrains commands through fixed adapters inside the backend container; per-call container isolation is a production hardening step.

