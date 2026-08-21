# Failure log

Every supported failure is an explicit state or evidence record. None is silently converted into success.

| Failure | Detection | Persisted signal | Result ceiling | Demo switch |
|---|---|---|---|---|
| Tool timeout | 10-second `asyncio` timeout | `TOOL_TIMEOUT` evidence + event | Human review | Fail web tool |
| Tool unavailable/nonzero/empty | Process boundary checks | `TOOL_UNAVAILABLE` or `TOOL_FAILED` | Human review | Fail web tool |
| Investigator outage | Provider timeout/error or injected failure | `MODEL_TIMEOUT` / `MODEL_UNAVAILABLE` event | Human review; no automated plan | Kill Investigator |
| Critic outage | Provider timeout/error or injected failure | Model failure event | Human review; validation prohibited | Kill Critic |
| Malformed model JSON | JSON + Pydantic validation, retry once | `MODEL_INVALID_OUTPUT` event | Human review | Malformed Critic JSON |
| Unauthorized target | Allowlist lookup | HTTP 403 + policy reason | No investigation created | API test |
| Tool-call budget | Counter before execution | `TOOL_BUDGET_EXCEEDED` | Human review | Unit test |
| Contradictory evidence | Critic detects opposing auth observations | Critic contradiction list | Human review | Evaluation S-08 |

## Expected live behavior

1. The happy path validates the admin exposure and missing response headers.
2. The Critic rejects the debug-route hypothesis because the unauthenticated probe returns HTTP 403.
3. Tool failure creates failure evidence for each affected hypothesis; the run completes in `HUMAN_REVIEW`.
4. Critic failure cannot preserve an earlier Investigator confidence as a final finding.
5. Invalid JSON fails twice and follows the same degraded path as a model outage.

The completed verification results are captured by the test suite and `evaluation/results/latest.json` when the evaluation runner is executed.
